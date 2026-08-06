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
PATH_AVALIACOES = "/api/avaliacoes"

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


def _serializar_chamado(chamado: sqlite3.Row, anotacoes=()) -> dict:
    quando = _dependencias["quando"]
    avaliacao_pendente = chamado["status"] == "concluido" and chamado["nota"] is None
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
            "nome": chamado["origem_usuario_nome"] or chamado["solicitante"],
            "email": chamado["origem_usuario_email"],
        },
        "avaliacao": {
            "pendente": avaliacao_pendente,
            "nota": chamado["nota"],
            "observacao": chamado["nota_obs"],
            "avaliado_em": chamado["nota_em"],
            "avaliado_em_formatado": (
                quando(chamado["nota_em"]) if chamado["nota_em"] else None
            ),
        },
        "andamento": [
            {
                "texto": anotacao["texto"],
                "criado_em": anotacao["criado_em"],
                "criado_em_formatado": quando(anotacao["criado_em"]),
            }
            for anotacao in anotacoes
        ],
    }


def _filtro_usuario(usuario_id: int, usuario_nome: str) -> tuple[str, list]:
    condicoes = ["(origem_sistema = ? AND origem_usuario_id = ?)"]
    argumentos = ["locarmais", usuario_id]
    usuario_nome = " ".join(usuario_nome.split())
    if usuario_nome:
        condicoes.append(
            "(origem_usuario_id IS NULL AND norm(solicitante) = norm(?))"
        )
        argumentos.append(usuario_nome)
    return "(" + " OR ".join(condicoes) + ")", argumentos


def _listar_chamados(usuario_id: int | None, usuario_nome: str = "") -> list[dict]:
    conn = _dependencias["get_db"]()
    try:
        where = ""
        argumentos = []
        if usuario_id is not None:
            filtro, argumentos = _filtro_usuario(usuario_id, usuario_nome)
            where = " WHERE " + filtro

        chamados = conn.execute(
            "SELECT * FROM solicitacoes" + where
            + " ORDER BY criado_em DESC, id DESC LIMIT 500",
            argumentos,
        ).fetchall()
        anotacoes_por_chamado = {}
        if chamados:
            marcadores = ",".join("?" for _ in chamados)
            anotacoes = conn.execute(
                f"SELECT * FROM anotacoes WHERE publica = 1 "
                f"AND solicitacao_id IN ({marcadores}) "
                "ORDER BY criado_em ASC, id ASC",
                [chamado["id"] for chamado in chamados],
            ).fetchall()
            for anotacao in anotacoes:
                anotacoes_por_chamado.setdefault(
                    anotacao["solicitacao_id"], []
                ).append(anotacao)
    finally:
        conn.close()

    return [
        _serializar_chamado(
            chamado, anotacoes_por_chamado.get(chamado["id"], [])
        )
        for chamado in chamados
    ]


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

    conn = _dependencias["get_db"]()
    try:
        filtro, argumentos = _filtro_usuario(usuario_id, nome)
        avaliacao_pendente = conn.execute(
            "SELECT id FROM solicitacoes WHERE " + filtro
            + " AND status = ? AND nota IS NULL "
            "ORDER BY concluido_em DESC, id DESC LIMIT 1",
            argumentos + ["concluido"],
        ).fetchone()
        if avaliacao_pendente is not None:
            return {}, {
                "avaliacao": (
                    "Avalie seu último chamado concluído antes de abrir outro."
                )
            }

        token = _dependencias["novo_token"]()
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


def _avaliar_chamado(payload: dict) -> tuple[dict, dict]:
    usuario = payload.get("usuario")
    if not isinstance(usuario, dict):
        return {}, {"usuario": "Os dados do usuário são obrigatórios."}

    usuario_id = usuario.get("id")
    usuario_nome = str(usuario.get("nome") or "").strip()
    chamado_id = payload.get("chamado_id")
    nota = payload.get("nota")
    observacao = str(payload.get("observacao") or "").strip()

    erros = {}
    if isinstance(usuario_id, bool) or not isinstance(usuario_id, int) or usuario_id <= 0:
        erros["usuario.id"] = "O identificador do usuário é inválido."
    if not usuario_nome or len(usuario_nome) > 255:
        erros["usuario.nome"] = "O nome do usuário é inválido."
    if isinstance(chamado_id, bool) or not isinstance(chamado_id, int) or chamado_id <= 0:
        erros["chamado_id"] = "O identificador do chamado é inválido."
    if isinstance(nota, bool) or not isinstance(nota, int) or nota not in range(1, 6):
        erros["nota"] = "A nota deve ser um número entre 1 e 5."
    if len(observacao) > 1000:
        erros["observacao"] = "A observação deve ter no máximo 1000 caracteres."
    if erros:
        return {}, erros

    conn = _dependencias["get_db"]()
    try:
        filtro, argumentos = _filtro_usuario(usuario_id, usuario_nome)
        chamado = conn.execute(
            "SELECT * FROM solicitacoes WHERE id = ? AND " + filtro,
            [chamado_id] + argumentos,
        ).fetchone()
        if chamado is None:
            return {}, {"chamado_id": "Chamado não encontrado para este usuário."}
        if chamado["status"] != "concluido":
            return {}, {"chamado_id": "O chamado ainda não foi concluído."}

        conn.execute(
            "UPDATE solicitacoes SET nota = ?, nota_obs = ?, "
            "nota_em = datetime('now') WHERE id = ?",
            (nota, observacao, chamado_id),
        )
        chamado = conn.execute(
            "SELECT * FROM solicitacoes WHERE id = ?", (chamado_id,)
        ).fetchone()
        anotacoes = conn.execute(
            "SELECT * FROM anotacoes WHERE solicitacao_id = ? AND publica = 1 "
            "ORDER BY criado_em ASC, id ASC",
            (chamado_id,),
        ).fetchall()
        conn.commit()
    finally:
        conn.close()

    return _serializar_chamado(chamado, anotacoes), {}


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
            "avaliacao": {
                "type": "object",
                "properties": {
                    "pendente": {"type": "boolean"},
                    "nota": {"type": ["integer", "null"], "minimum": 1, "maximum": 5},
                    "observacao": {"type": "string"},
                    "avaliado_em": {"type": ["string", "null"]},
                    "avaliado_em_formatado": {"type": ["string", "null"]},
                },
            },
            "andamento": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "texto": {"type": "string"},
                        "criado_em": {"type": "string"},
                        "criado_em_formatado": {"type": "string"},
                    },
                },
            },
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
            "version": "1.3.0",
            "description": "API privada para criação e acompanhamento de chamados do LocarMais.",
        },
        "servers": [{"url": "/", "description": "Servidor atual"}],
        "paths": {
            "/api/chamados": {
                "get": {
                    "summary": "Listar chamados",
                    "description": "Com usuario_id, lista os chamados vinculados ao ID e os manuais sem origem cujo solicitante corresponda a usuario_nome. Sem os parâmetros, lista todos os chamados.",
                    "security": [{"bearerAuth": []}],
                    "parameters": [
                        {
                            "name": "usuario_id", "in": "query", "required": False,
                            "schema": {"type": "integer", "minimum": 1},
                        },
                        {
                            "name": "usuario_nome", "in": "query", "required": False,
                            "schema": {"type": "string", "maxLength": 255},
                        },
                    ],
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
            },
            "/api/avaliacoes": {
                "post": {
                    "summary": "Avaliar chamado",
                    "description": "Registra a nota de um chamado concluído pertencente ao usuário autenticado no LocarMais.",
                    "security": [{"bearerAuth": []}],
                    "requestBody": {
                        "required": True,
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "required": ["usuario", "chamado_id", "nota"],
                            "properties": {
                                "usuario": esquema_usuario,
                                "chamado_id": {"type": "integer", "minimum": 1},
                                "nota": {"type": "integer", "minimum": 1, "maximum": 5},
                                "observacao": {"type": "string", "maxLength": 1000},
                            },
                        }}},
                    },
                    "responses": {
                        "200": {
                            "description": "Avaliação registrada",
                            "content": {"application/json": {"schema": {
                                "type": "object", "properties": {"dados": esquema_chamado},
                            }}},
                        },
                        "400": resposta_erro,
                        "401": resposta_erro,
                        "422": resposta_erro,
                        "503": resposta_erro,
                    },
                }
            },
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
    usuario_nome = (query.get("usuario_nome", [""])[0] or "").strip()
    if bruto and (not bruto.isdigit() or int(bruto) <= 0):
        _enviar_json(handler, {"mensagem": "usuario_id inválido."}, 422)
        return True
    if len(usuario_nome) > 255:
        _enviar_json(handler, {"mensagem": "usuario_nome inválido."}, 422)
        return True

    usuario_id = int(bruto) if bruto else None
    _enviar_json(handler, {"dados": _listar_chamados(usuario_id, usuario_nome)})
    return True


def atender_post(handler, url) -> bool:
    if url.path not in (PATH_CHAMADOS, PATH_AVALIACOES):
        return False
    if not _autorizada(handler):
        return True

    payload, erro = _ler_json(handler)
    if erro:
        status = 413 if "excede" in erro else 400
        _enviar_json(handler, {"mensagem": erro}, status)
        return True

    if url.path == PATH_AVALIACOES:
        chamado, erros = _avaliar_chamado(payload)
        if erros:
            _enviar_json(
                handler,
                {"mensagem": "Não foi possível registrar a avaliação.", "erros": erros},
                422,
            )
            return True

        _enviar_json(
            handler,
            {"dados": chamado, "mensagem": "Avaliação registrada. Obrigado!"},
        )
        return True

    chamado, erros = _criar_chamado(payload)
    if erros:
        _enviar_json(
            handler,
            {
                "mensagem": erros.get("avaliacao", "Revise os dados enviados."),
                "erros": erros,
            },
            422,
        )
        return True

    _enviar_json(handler, {"dados": chamado}, 201)
    return True
