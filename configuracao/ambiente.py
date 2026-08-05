"""Carregamento das variáveis locais sem dependências externas."""

import os
from pathlib import Path


CAMINHO_ENV = Path(__file__).resolve().parent.parent / ".env"


def carregar_ambiente(caminho: Path = CAMINHO_ENV) -> None:
    """Carrega o .env sem substituir variáveis já definidas pelo processo."""
    if not caminho.is_file():
        return

    for linha_bruta in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha_bruta.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue

        chave, valor = linha.split("=", 1)
        chave = chave.strip()
        valor = valor.strip()
        if not chave.replace("_", "").isalnum() or chave[0].isdigit():
            continue

        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in ("'", '"'):
            valor = valor[1:-1]

        os.environ.setdefault(chave, valor)
