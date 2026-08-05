#!/usr/bin/env python3
"""Copia o banco SQLite local para um PostgreSQL vazio, preservando IDs e tokens."""

import sqlite3
import sys
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from configuracao.ambiente import carregar_ambiente

carregar_ambiente()

import app
from configuracao.banco import usa_postgres


COLUNAS_SOLICITACOES = (
    "id",
    "solicitante",
    "assunto",
    "descricao",
    "prioridade",
    "status",
    "criado_em",
    "concluido_em",
    "fila",
    "dev",
    "previsao",
    "categoria",
    "token",
    "nota",
    "nota_obs",
    "nota_em",
    "origem_sistema",
    "origem_usuario_id",
    "origem_usuario_nome",
    "origem_usuario_email",
)
COLUNAS_ANOTACOES = ("id", "solicitacao_id", "texto", "criado_em", "publica")


def copiar_tabela(origem, destino, tabela: str, colunas: tuple[str, ...]) -> int:
    nomes = ", ".join(colunas)
    marcadores = ", ".join("?" for _ in colunas)
    linhas = origem.execute(f"SELECT {nomes} FROM {tabela} ORDER BY id").fetchall()
    for linha in linhas:
        destino.execute(
            f"INSERT INTO {tabela} ({nomes}) VALUES ({marcadores})",
            tuple(linha[coluna] for coluna in colunas),
        )
    return len(linhas)


def ajustar_sequencia(destino, tabela: str) -> None:
    destino.execute(
        f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
        f"COALESCE(MAX(id), 1), COUNT(*) > 0) FROM {tabela}"
    )


def main() -> None:
    if not usa_postgres():
        raise SystemExit("Configure DATABASE_URL no .env antes de executar a migração.")
    if not Path(app.DB_PATH).is_file():
        raise SystemExit(f"Banco SQLite não encontrado em {app.DB_PATH}.")

    app.init_db()
    origem = sqlite3.connect(app.DB_PATH)
    origem.row_factory = sqlite3.Row
    destino = app.get_db()
    try:
        totais_destino = {
            tabela: destino.execute(f"SELECT COUNT(*) FROM {tabela}").fetchone()[0]
            for tabela in ("solicitacoes", "anotacoes")
        }
        if any(totais_destino.values()):
            raise RuntimeError(
                "Migração cancelada: o PostgreSQL já contém registros. "
                "Nenhum dado foi alterado."
            )

        total_solicitacoes = copiar_tabela(
            origem, destino, "solicitacoes", COLUNAS_SOLICITACOES
        )
        total_anotacoes = copiar_tabela(
            origem, destino, "anotacoes", COLUNAS_ANOTACOES
        )
        ajustar_sequencia(destino, "solicitacoes")
        ajustar_sequencia(destino, "anotacoes")
        destino.commit()
    except Exception:
        destino.rollback()
        raise
    finally:
        destino.close()
        origem.close()

    print(
        "Migração concluída: "
        f"{total_solicitacoes} solicitação(ões) e {total_anotacoes} anotação(ões)."
    )


if __name__ == "__main__":
    main()
