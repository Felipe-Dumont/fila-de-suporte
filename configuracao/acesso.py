"""Credenciais opcionais para proteger as telas internas em hospedagem pública."""

import base64
import os
import secrets


USUARIO_ADMIN = os.environ.get("SOLICITAMAIS_ADMIN_USUARIO", "").strip()
SENHA_ADMIN = os.environ.get("SOLICITAMAIS_ADMIN_SENHA", "")


def acesso_configurado() -> bool:
    return bool(USUARIO_ADMIN and SENHA_ADMIN)


def configuracao_incompleta() -> bool:
    return bool(USUARIO_ADMIN) != bool(SENHA_ADMIN)


def credenciais_validas(autorizacao: str) -> bool:
    if not acesso_configurado() or not autorizacao.startswith("Basic "):
        return False

    try:
        decodificado = base64.b64decode(
            autorizacao[6:].strip(), validate=True
        ).decode("utf-8")
        usuario, senha = decodificado.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False

    return secrets.compare_digest(usuario, USUARIO_ADMIN) and secrets.compare_digest(
        senha, SENHA_ADMIN
    )
