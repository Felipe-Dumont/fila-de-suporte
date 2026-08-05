"""Conexões com SQLite local ou PostgreSQL/Supabase em produção."""

import os
import re
from collections.abc import Iterator, Sequence
from typing import Any


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def usa_postgres() -> bool:
    return DATABASE_URL.startswith(("postgres://", "postgresql://"))


class LinhaBanco(Sequence):
    """Linha compatível com acesso posicional e por nome, como sqlite3.Row."""

    def __init__(self, nomes: tuple[str, ...], valores: Sequence[Any]) -> None:
        self._nomes = nomes
        self._valores = tuple(valores)
        self._indices = {nome: indice for indice, nome in enumerate(nomes)}

    def __getitem__(self, chave):
        if isinstance(chave, str):
            return self._valores[self._indices[chave]]
        return self._valores[chave]

    def __iter__(self) -> Iterator[Any]:
        return iter(self._valores)

    def __len__(self) -> int:
        return len(self._valores)

    def keys(self) -> tuple[str, ...]:
        return self._nomes


def _fabrica_linha(cursor):
    if cursor.description is None:
        return tuple

    nomes = tuple(coluna.name for coluna in cursor.description)

    def criar_linha(valores):
        return LinhaBanco(nomes, valores)

    return criar_linha


def _adaptar_sql_postgres(sql: str) -> str:
    """Converte o pequeno subconjunto SQLite ainda usado pelas regras do app."""
    adaptado = sql.replace("?", "%s")
    adaptado = adaptado.replace(
        "datetime('now')",
        "to_char(timezone('UTC', CURRENT_TIMESTAMP), 'YYYY-MM-DD HH24:MI:SS')",
    )
    adaptado = re.sub(r"\s+COLLATE\s+NOCASE", "", adaptado, flags=re.IGNORECASE)
    adaptado = re.sub(
        r"COALESCE\(SUM\(status\s*=\s*%s\),\s*0\)",
        "COALESCE(SUM(CASE WHEN status = %s THEN 1 ELSE 0 END), 0)",
        adaptado,
        flags=re.IGNORECASE,
    )
    return adaptado


class ConexaoPostgres:
    def __init__(self, conexao) -> None:
        self._conexao = conexao

    def execute(self, sql: str, parametros: Sequence[Any] = ()):
        return self._conexao.execute(
            _adaptar_sql_postgres(sql), tuple(parametros), prepare=False
        )

    def commit(self) -> None:
        self._conexao.commit()

    def rollback(self) -> None:
        self._conexao.rollback()

    def close(self) -> None:
        self._conexao.close()


def conectar_postgres() -> ConexaoPostgres:
    try:
        import psycopg
    except ImportError as erro:
        raise RuntimeError(
            "A dependência psycopg não está instalada. Execute: pip install -r requirements.txt"
        ) from erro

    opcoes = {
        "connect_timeout": 10,
        "prepare_threshold": None,
        "row_factory": _fabrica_linha,
    }
    if "sslmode=" not in DATABASE_URL:
        opcoes["sslmode"] = "require"

    conexao = psycopg.connect(DATABASE_URL, **opcoes)
    return ConexaoPostgres(conexao)
