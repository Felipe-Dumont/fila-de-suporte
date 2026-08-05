"""Configuração da API privada consumida pelo LocarMais."""

import os

TOKEN_API = os.environ.get("SOLICITAMAIS_API_TOKEN", "").strip()
LIMITE_PAYLOAD_BYTES = 64 * 1024
