"""Rotas e operações da API privada consumida pelo LocarMais."""

import json
import secrets
import sqlite3
from urllib.parse import parse_qs

from configuracao.api import LIMITE_PAYLOAD_BYTES, TOKEN_API
from views.api.pagina import render_documentacao_api


PATH_DOCUMENTACAO_API = "/api"
PATH_DOCUMENTACAO_API_ALTERNATIVO = "/api/documentacao"
PATH_OPENAPI = "/api/openapi.json"
PATH_CHAMADOS = "/api/chamados"

_dependencias = {}


def configurar(dependencias: dict) -> None:
    global _dependencias
    _dependencias = dependencias


def _enviar_json(handler, payload: dict, status: int = 200) -> None:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(data)


def _enviar_html(handler, conteudo: str, status: int = 200) -> None:
    data = conteudo.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def _autorizada(handler) -> bool:
    if not TOKEN_API:
        _enviar_json(
            handler,
            {"mensagem": "A API do SolicitaMais não está configurada."},
            503,
        )
        return False

    autorizacao = handler.headers.get("Authorization", "")
    prefixo = "Bearer "
    recebido = autorizacao[len(prefixo):] if autorizacao.startswith(prefixo) else ""
    if not recebido or not secrets.compare_digest(recebido, TOKEN_API):
        _enviar_json(handler, {"mensagem": "Não autorizado."}, 401)
        return False

    return True


def _ler_json(handler) -> tuple[dict | None, str]:
    try:
        tamanho = int(handler.headers.get("Content-Length", 0))
    except (TypeError, ValueError):
        return None, "O cabeçalho Content-Length é inválido."
    if tamanho <= 0:
        return None, "O corpo JSON é obrigatório."
    if tamanho > LIMITE_PAYLOAD_BYTES:
        return None, "O corpo da requisição excede o limite permitido."

    try:
        payload = json.loads(handler.rfile.read(tamanho).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "O corpo JSON é inválido."

    if not isinstance(payload, dict):
        return None, "O corpo JSON deve ser um objeto."

    return payload, ""


def _serializar_chamado(chamado: sqlite3.Row) -> dict:
    quando = _dependencias["quando"]
    return {
        "id": chamado["id"],
        "assunto": chamado["assunto"],
        "descricao": chamado["descricao"],
        "categoria": chamado["fila"],
        "prioridade": chamado["prioridade"],
        "status": chamado["status"],
        "responsavel": chamado["dev"],
        "previsao": chamado["previsao"],
        "criado_em": chamado["criado_em"],
        "criado_em_formatado": quando(chamado["criado_em"]),
        "concluido_em": chamado["concluido_em"],
        "concluido_em_formatado": (
            quando(chamado["concluido_em"]) if chamado["concluido_em"] else None
        ),
        "usuario": {
            "id": chamado["origem_usuario_id"],
            "nome": chamado["origem_usuario_nome"],
            "email": chamado["origem_usuario_email"],
        },
    }


def _listar_chamados(usuario_id: int | None) -> list[dict]:
    conn = _dependencias["get_db"]()
    try:
        condicoes = ["origem_sistema = ?"]
        argumentos = ["locarmais"]
        if usuario_id is not None:
            condicoes.append("origem_usuario_id = ?")
            argumentos.append(usuario_id)

        chamados = conn.execute(
            "SELECT * FROM solicitacoes WHERE " + " AND ".join(condicoes)
            + " ORDER BY criado_em DESC, id DESC LIMIT 500",
            argumentos,
        ).fetchall()
    finally:
        conn.close()

    return [_serializar_chamado(chamado) for chamado in chamados]


def _criar_chamado(payload: dict) -> tuple[dict, dict]:
    usuario = payload.get("usuario")
    if not isinstance(usuario, dict):
        return {}, {"usuario": "Os dados do usuário são obrigatórios."}

    usuario_id = usuario.get("id")
    nome = str(usuario.get("nome") or "").strip()
    email = str(usuario.get("email") or "").strip()
    fila = str(payload.get("categoria") or "").strip()
    assunto = str(payload.get("assunto") or "").strip()
    descricao = str(payload.get("descricao") or "").strip()

    erros = {}
    if isinstance(usuario_id, bool) or not isinstance(usuario_id, int) or usuario_id <= 0:
        erros["usuario.id"] = "O identificador do usuário é inválido."
    if not nome or len(nome) > 255:
        erros["usuario.nome"] = "O nome deve ter entre 1 e 255 caracteres."
    if len(email) > 255:
        erros["usuario.email"] = "O e-mail deve ter no máximo 255 caracteres."
    if fila not in _dependencias["filas"]:
        erros["categoria"] = "Selecione Suporte ou Demanda."
    if not assunto or len(assunto) > 160:
        erros["assunto"] = "O assunto deve ter entre 1 e 160 caracteres."
    if len(descricao) > 2000:
        erros["descricao"] = "Os detalhes devem ter no máximo 2000 caracteres."

    if erros:
        return {}, erros

    token = _dependencias["novo_token"]()
    conn = _dependencias["get_db"]()
    try:
        chamado_id = conn.execute(
            "INSERT INTO solicitacoes "
            "(solicitante, assunto, descricao, prioridade, fila, token, "
            "origem_sistema, origem_usuario_id, origem_usuario_nome, "
            "origem_usuario_email) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "RETURNING id",
            (
                nome, assunto, descricao, "normal", fila, token, "locarmais",
                usuario_id, nome, email,
            ),
        ).fetchone()["id"]
        chamado = conn.execute(
            "SELECT * FROM solicitacoes WHERE id = ?", (chamado_id,)
        ).fetchone()
        conn.commit()
    finally:
        conn.close()

    return _serializar_chamado(chamado), {}


def _especificacao_openapi() -> dict:
    esquema_usuario = {
        "type": "object",
        "required": ["id", "nome"],
        "properties": {
            "id": {"type": "integer", "minimum": 1, "example": 123},
            "nome": {"type": "string", "maxLength": 255, "example": "Maria da Silva"},
            "email": {"type": "string", "maxLength": 255, "example": "maria@locarmais.com.br"},
        },
    }
    esquema_chamado = {
        "type": "object",
        "properties": {
            "id": {"type": "integer", "example": 42},
            "assunto": {"type": "string"},
            "descricao": {"type": "string"},
            "categoria": {"type": "string", "enum": ["suporte", "demandas"]},
            "prioridade": {"type": "string", "enum": ["baixa", "normal", "alta"]},
            "status": {"type": "string", "enum": ["na_fila", "em_atendimento", "concluido"]},
            "responsavel": {"type": "string"},
            "previsao": {"type": ["string", "null"], "format": "date"},
            "criado_em": {"type": "string"},
            "criado_em_formatado": {"type": "string"},
            "concluido_em": {"type": ["string", "null"]},
            "concluido_em_formatado": {"type": ["string", "null"]},
            "usuario": esquema_usuario,
        },
    }
    resposta_erro = {
        "description": "Erro",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {"mensagem": {"type": "string"}},
                }
            }
        },
    }

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "SolicitaMais API",
            "version": "1.0.0",
            "description": "API privada para criação e acompanhamento de chamados do LocarMais.",
        },
        "servers": [{"url": "/", "description": "Servidor atual"}],
        "paths": {
            "/api/chamados": {
                "get": {
                    "summary": "Listar chamados",
                    "description": "Com usuario_id, lista somente o usuário. Sem o parâmetro, lista todos os chamados do LocarMais.",
                    "security": [{"bearerAuth": []}],
                    "parameters": [{
                        "name": "usuario_id", "in": "query", "required": False,
                        "schema": {"type": "integer", "minimum": 1},
                    }],
                    "responses": {
                        "200": {
                            "description": "Lista de chamados",
                            "content": {"application/json": {"schema": {
                                "type": "object",
                                "properties": {"dados": {"type": "array", "items": esquema_chamado}},
                            }}},
                        },
                        "401": resposta_erro,
                        "422": resposta_erro,
                        "503": resposta_erro,
                    },
                },
                "post": {
                    "summary": "Criar chamado",
                    "security": [{"bearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["usuario", "categoria", "assunto"],
                            "properties": {
                                "usuario": esquema_usuario,
                                "categoria": {"type": "string", "enum": ["suporte", "demandas"]},
                                "assunto": {"type": "string", "minLength": 1, "maxLength": 160},
                                "descricao": {"type": "string", "maxLength": 2000},
                            },
                        }}},
                    },
                    "responses": {
                        "201": {
                            "description": "Chamado criado",
                            "content": {"application/json": {"schema": {
                                "type": "object", "properties": {"dados": esquema_chamado},
                            }}},
                        },
                        "400": resposta_erro,
                        "401": resposta_erro,
                        "413": resposta_erro,
                        "422": resposta_erro,
                        "503": resposta_erro,
                    },
                },
            }
        },
        "components": {
            "securitySchemes": {
                "bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "token"}
            }
        },
    }


def atender_get(handler, url) -> bool:
    if url.path in (PATH_DOCUMENTACAO_API, PATH_DOCUMENTACAO_API_ALTERNATIVO):
        _enviar_html(handler, render_documentacao_api(bool(TOKEN_API)))
        return True
    if url.path == PATH_OPENAPI:
        _enviar_json(handler, _especificacao_openapi())
        return True
    if url.path != PATH_CHAMADOS:
        return False
    if not _autorizada(handler):
        return True

    query = parse_qs(url.query)
    bruto = (query.get("usuario_id", [""])[0] or "").strip()
    if bruto and (not bruto.isdigit() or int(bruto) <= 0):
        _enviar_json(handler, {"mensagem": "usuario_id inválido."}, 422)
        return True

    usuario_id = int(bruto) if bruto else None
    _enviar_json(handler, {"dados": _listar_chamados(usuario_id)})
    return True


def atender_post(handler, url) -> bool:
    if url.path != PATH_CHAMADOS:
        return False
    if not _autorizada(handler):
        return True

    payload, erro = _ler_json(handler)
    if erro:
        status = 413 if "excede" in erro else 400
        _enviar_json(handler, {"mensagem": erro}, status)
        return True

    chamado, erros = _criar_chamado(payload)
    if erros:
        _enviar_json(
            handler,
            {"mensagem": "Revise os dados enviados.", "erros": erros},
            422,
        )
        return True

    _enviar_json(handler, {"dados": chamado}, 201)
    return True
