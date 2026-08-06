"""Rotas de consulta e movimentação do quadro Kanban."""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from views.kanban.pagina import render_kanban


PATH_KANBAN = "/kanban"
PATH_MOVER_KANBAN = "/kanban/mover"
DESTINOS = ("pendente", "atribuido", "andamento", "concluido")
LIMITE_PAYLOAD_BYTES = 16 * 1024
DIAS_CONCLUIDOS_KANBAN = 5

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


def _ler_filtros(query: str) -> dict:
    params = parse_qs(query, keep_blank_values=True)

    def obter(nome: str) -> str:
        return (params.get(nome, [""])[0] or "").strip()

    fila = obter("fila")
    return {
        "q": obter("q"),
        "fila": fila if fila in _dependencias["filas"] else "",
        "resp": obter("resp"),
        "cat": obter("cat"),
    }


def _buscar_dados(filtros: dict) -> tuple:
    conn = _dependencias["get_db"]()
    try:
        corte_concluidos = (
            datetime.now(timezone.utc) - timedelta(days=DIAS_CONCLUIDOS_KANBAN)
        ).strftime("%Y-%m-%d %H:%M:%S")
        condicoes = ["(status <> ? OR concluido_em >= ?)"]
        argumentos = [_dependencias["status_concluido"], corte_concluidos]
        if filtros["q"]:
            alvo = _dependencias["normalizar"](filtros["q"])
            alvo = alvo.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            condicoes.append(
                "(norm(solicitante) LIKE ? ESCAPE '\\' "
                "OR norm(assunto) LIKE ? ESCAPE '\\' "
                "OR norm(descricao) LIKE ? ESCAPE '\\')"
            )
            argumentos.extend([f"%{alvo}%"] * 3)
        if filtros["fila"]:
            condicoes.append("fila = ?")
            argumentos.append(filtros["fila"])
        if filtros["resp"]:
            if filtros["resp"] == "—":
                condicoes.append("dev = ''")
            else:
                condicoes.append("dev = ?")
                argumentos.append(filtros["resp"])
        if filtros["cat"]:
            condicoes.append("categoria = ?")
            argumentos.append(filtros["cat"])

        where = " WHERE " + " AND ".join(condicoes) if condicoes else ""
        chamados = conn.execute(
            "SELECT * FROM solicitacoes" + where
            + " ORDER BY criado_em ASC, id ASC",
            argumentos,
        ).fetchall()
        responsaveis = [
            row[0] for row in conn.execute(
                "SELECT DISTINCT dev FROM solicitacoes WHERE dev <> '' "
                "ORDER BY dev COLLATE NOCASE"
            )
        ]
        categorias = [
            row[0] for row in conn.execute(
                "SELECT DISTINCT categoria FROM solicitacoes WHERE categoria <> '' "
                "ORDER BY categoria COLLATE NOCASE"
            )
        ]
        por_fila = dict(conn.execute(
            "SELECT fila, COUNT(*) FROM solicitacoes WHERE status IN (?, ?) GROUP BY fila",
            (_dependencias["status_fila"], _dependencias["status_atendimento"]),
        ).fetchall())
        alertas = _dependencias["buscar_alertas"](conn)
    finally:
        conn.close()

    return chamados, responsaveis, categorias, por_fila, alertas


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


def _mover_chamado(payload: dict) -> tuple[dict, str, int]:
    chamado_id = payload.get("id")
    destino = str(payload.get("destino") or "").strip()
    responsavel_enviado = str(payload.get("responsavel") or "").strip()[:80]

    if isinstance(chamado_id, bool) or not isinstance(chamado_id, int) or chamado_id <= 0:
        return {}, "O identificador do chamado é inválido.", 422
    if destino not in DESTINOS:
        return {}, "A coluna de destino é inválida.", 422

    conn = _dependencias["get_db"]()
    try:
        chamado = conn.execute(
            "SELECT id, dev FROM solicitacoes WHERE id = ?", (chamado_id,)
        ).fetchone()
        if chamado is None:
            return {}, "Chamado não encontrado.", 404

        responsavel = _dependencias["canonizar"](
            conn, "dev", responsavel_enviado or chamado["dev"]
        )
        if destino in ("atribuido", "andamento") and not responsavel:
            return {}, "Informe um responsável para mover para esta coluna.", 422

        if destino == "pendente":
            responsavel = ""
            status = _dependencias["status_fila"]
            conn.execute(
                "UPDATE solicitacoes SET status = ?, dev = ?, concluido_em = NULL WHERE id = ?",
                (status, responsavel, chamado_id),
            )
        elif destino == "atribuido":
            status = _dependencias["status_fila"]
            conn.execute(
                "UPDATE solicitacoes SET status = ?, dev = ?, concluido_em = NULL WHERE id = ?",
                (status, responsavel, chamado_id),
            )
        elif destino == "andamento":
            status = _dependencias["status_atendimento"]
            conn.execute(
                "UPDATE solicitacoes SET status = ?, dev = ?, concluido_em = NULL WHERE id = ?",
                (status, responsavel, chamado_id),
            )
        else:
            status = _dependencias["status_concluido"]
            conn.execute(
                "UPDATE solicitacoes SET status = ?, dev = ?, "
                "concluido_em = datetime('now') WHERE id = ?",
                (status, responsavel, chamado_id),
            )

        conn.commit()
    finally:
        conn.close()

    return {
        "id": chamado_id,
        "destino": destino,
        "status": status,
        "responsavel": responsavel,
    }, "", 200


def atender_get(handler, url) -> bool:
    if url.path != PATH_KANBAN:
        return False

    filtros = _ler_filtros(url.query)
    chamados, responsaveis, categorias, por_fila, alertas = _buscar_dados(filtros)
    corpo = render_kanban(
        chamados, filtros, responsaveis, categorias, _dependencias["quando"]
    )
    contadores = (
        f'<div class="counts"><b>{len(chamados)}</b> chamados no quadro</div>'
    )
    pagina = _dependencias["shell"](
        "Kanban",
        "Visualize o fluxo completo e mova os chamados conforme o trabalho avança.",
        contadores,
        _dependencias["render_abas"](PATH_KANBAN, por_fila, alertas["total"]),
        "",
        corpo,
    )
    handler._send_html(pagina)
    return True


def atender_post(handler, url) -> bool:
    if url.path != PATH_MOVER_KANBAN:
        return False

    payload, erro = _ler_json(handler)
    if erro:
        _enviar_json(handler, {"mensagem": erro}, 400)
        return True

    dados, mensagem, status = _mover_chamado(payload)
    if mensagem:
        _enviar_json(handler, {"mensagem": mensagem}, status)
        return True

    _enviar_json(handler, {"dados": dados, "mensagem": "Chamado atualizado."})
    return True
