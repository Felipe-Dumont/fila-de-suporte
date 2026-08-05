"""Componentes visuais compartilhados entre as telas."""

import sqlite3


def configurar(dependencias: dict) -> None:
    globals().update(
        {nome: valor for nome, valor in dependencias.items() if not nome.startswith("__")}
    )


def render_notas(s: sqlite3.Row, notas: list, ocultos: str) -> str:
    """Histórico do ticket + campo pra registrar o próximo andamento."""
    itens = ""
    for n in notas:
        publica = bool(n["publica"])
        marca = ('<span class="tag vis">visível pro solicitante</span>' if publica
                 else '<span class="tag plain">interna</span>')
        itens += f"""
                <div class="nota">
                    <div class="cab">
                        <span class="qdo mono">{quando(n['criado_em'])}</span>
                        {marca}
                        <form class="inline" method="post">
                            <input type="hidden" name="action" value="nota_visivel">
                            <input type="hidden" name="nota" value="{n['id']}">
                            {ocultos}
                            <button class="btn ghost" type="submit">{
                                "tornar interna" if publica else "tornar visível"}</button>
                        </form>
                        <form class="inline" method="post">
                            <input type="hidden" name="action" value="apagar_nota">
                            <input type="hidden" name="nota" value="{n['id']}">
                            {ocultos}
                            <button class="btn ghost danger" type="submit">apagar</button>
                        </form>
                    </div>
                    <div class="txt">{e(n['texto'])}</div>
                </div>"""
    if not itens:
        itens = '<p class="hint" style="margin:0;color:#64717f;font-size:13px;">Nada registrado ainda.</p>'

    return f"""
            <details class="tool">
                <summary>Anotações ({len(notas)})</summary>
                <div class="painel">
                    {itens}
                    <form class="nova-nota" method="post">
                        <input type="hidden" name="action" value="anotar">
                        <input type="hidden" name="id" value="{s['id']}">
                        {ocultos}
                        <textarea name="texto" required maxlength="1000"
                                  placeholder="O que aconteceu? Ex.: liguei, aguardando o jurídico"></textarea>
                        <label class="check">
                            <input type="checkbox" name="publica" value="1">
                            mostrar pro solicitante no link de acompanhamento
                        </label>
                        <button class="btn ghost" type="submit">Anotar</button>
                    </form>
                </div>
            </details>"""


def render_edicao(s: sqlite3.Row, ocultos: str, lista_cat: str) -> str:
    opts_prio = "".join(
        f'<option value="{p}"{" selected" if s["prioridade"] == p else ""}>'
        f"{p.capitalize()}</option>"
        for p in PRIORIDADES
    )
    return f"""
            <details class="tool">
                <summary>Editar</summary>
                <form class="painel" method="post">
                    <input type="hidden" name="action" value="editar">
                    <input type="hidden" name="id" value="{s['id']}">
                    {ocultos}
                    <label>Assunto</label>
                    <input name="assunto" required maxlength="160" value="{e(s['assunto'])}">
                    <label>Detalhes</label>
                    <textarea name="descricao" maxlength="2000">{e(s['descricao'])}</textarea>
                    <div class="linha2">
                        <div>
                            <label>Solicitante</label>
                            <input name="solicitante" required maxlength="120"
                                   value="{e(s['solicitante'])}">
                        </div>
                        <div>
                            <label>Categoria</label>
                            <input name="categoria" maxlength="60" list="{lista_cat}"
                                   value="{e(s['categoria'])}" placeholder="Ex.: Contratos">
                        </div>
                        <div>
                            <label>Prioridade</label>
                            <select name="prioridade">{opts_prio}</select>
                        </div>
                    </div>
                    <button class="btn primary" type="submit">Salvar alterações</button>
                </form>
            </details>"""


def render_ticket(pos: int, s: sqlite3.Row, ocultos: str, fila: str,
                  notas: list = (), lista_cat: str = "cats",
                  lista_resp: str = "resps") -> str:
    is_next = pos == 1
    em_atend = s["status"] == STATUS_ATENDIMENTO
    demanda = fila == FILA_DEMANDAS

    alerta = em_alerta(s, fila)

    eyebrow = '<div class="eyebrow">Próximo</div>' if is_next else ""
    desc = f'<p class="desc">{e(s["descricao"])}</p>' if s["descricao"] else ""

    if not alerta:
        alerta_tag = ""
    elif demanda:
        alerta_tag = '<span class="tag alta">⚠ Venceu sem iniciar</span>'
    else:
        alerta_tag = f'<span class="tag alta">⚠ Parada há {duracao(s["criado_em"])}</span>'

    if em_atend:
        status_tag = f'<span class="tag live">{FILAS[fila]["tag_ativo"]}</span>'
    else:
        status_tag = f'<span class="tag wait">{FILAS[fila]["tag_espera"]}</span>'

    if s["prioridade"] == "alta":
        prio_tag = '<span class="tag alta">Prioridade alta</span>'
    elif s["prioridade"] == "baixa":
        prio_tag = '<span class="tag plain">Prioridade baixa</span>'
    else:
        prio_tag = ""

    cat_tag = f'<span class="tag cat">{e(s["categoria"])}</span>' if s["categoria"] else ""

    # responsável vale nas duas filas; previsão só nas demandas
    conf = FILAS[fila]
    if s["dev"]:
        extra_tags = f'<span class="tag dev">{e(s["dev"])}</span>'
    else:
        extra_tags = f'<span class="tag plain">{conf["resp_sem"]}</span>'

    campo_previsao = ""
    if demanda:
        if s["previsao"]:
            txt, classe = prazo(s["previsao"])
            if txt:
                extra_tags += f'<span class="tag {classe}">{e(txt)}</span>'
        else:
            extra_tags += '<span class="tag plain">Sem previsão</span>'
        campo_previsao = f'<input type="date" name="previsao" value="{e(s["previsao"])}">'

    assign = f"""
            <form class="assign" method="post">
                <input type="hidden" name="action" value="atribuir">
                <input type="hidden" name="id" value="{s['id']}">
                {ocultos}
                <input name="dev" value="{e(s['dev'])}" maxlength="80"
                       list="{lista_resp}" placeholder="{conf['resp_ph']}">
                {campo_previsao}
                <button class="btn ghost" type="submit">Salvar</button>
            </form>"""

    iniciar_btn = ""
    if not em_atend:
        iniciar_btn = f"""
            <form class="inline" method="post">
                <input type="hidden" name="action" value="atender">
                <input type="hidden" name="id" value="{s['id']}">
                {ocultos}
                <button class="btn ghost" type="submit">{FILAS[fila]['iniciar']}</button>
            </form>"""

    return f"""
    <article class="ticket {'next' if is_next else ''} {'alert' if alerta else ''}">
        <div class="pos"><span class="n mono">{pos}</span></div>
        <div class="body">
            {eyebrow}
            <div class="title">{e(s['assunto'])}</div>
            <div class="meta">
                {e(s['solicitante'])} ·
                #{s['id']} ·
                <span class="mono">{quando(s['criado_em'])}</span> ·
                {e(esperando_desde(s['criado_em']))}
            </div>
            {desc}
            <div class="tags">{alerta_tag}{status_tag}{cat_tag}{prio_tag}{extra_tags}</div>
            <div class="actions">
                {iniciar_btn}
                <form class="inline" method="post">
                    <input type="hidden" name="action" value="concluir">
                    <input type="hidden" name="id" value="{s['id']}">
                    {ocultos}
                    <button class="btn ghost" type="submit">Concluir</button>
                </form>
                <form class="inline" method="post" onsubmit="return confirm('Excluir esta solicitação?')">
                    <input type="hidden" name="action" value="excluir">
                    <input type="hidden" name="id" value="{s['id']}">
                    {ocultos}
                    <button class="btn ghost danger" type="submit">Excluir</button>
                </form>
            </div>
            <div class="tools">
                {render_edicao(s, ocultos, lista_cat)}
                {render_notas(s, list(notas), ocultos)}
            </div>
            {assign}
        </div>
    </article>"""


def render_share(s: sqlite3.Row) -> str:
    """Caixa com o link de avaliação de um item concluído.

    A URL é montada no navegador (`share-url`): o servidor não sabe por qual
    endereço você chegou — localhost numa máquina, IP da rede na outra.
    """
    if not s["token"]:
        return ""
    caminho = f"{PATH_AVALIAR}?t={s['token']}"
    if s["nota"]:
        txt = f'Avaliado em {quando(s["nota_em"])} · {s["nota"]}/5'
        if s["nota_obs"]:
            txt += f' · “{e(s["nota_obs"])}”'
        aviso = f'<p class="obs">{txt}</p>'
    else:
        aviso = '<p class="obs">Ainda sem avaliação. Mande o link pro solicitante.</p>'
    return f"""
                <details class="share">
                    <summary>Compartilhar</summary>
                    <div class="share-box">
                        <input class="share-url" data-p="{e(caminho)}" readonly
                               value="{e(caminho)}" onclick="this.select()"
                               aria-label="Link de avaliação">
                        <button class="btn ghost" type="button" onclick="copiar(this)">Copiar</button>
                        <a class="btn ghost" href="{e(caminho)}" target="_blank" rel="noopener">Abrir</a>
                        {aviso}
                    </div>
                </details>"""


def render_concluidos(rows, ocultos: str, notas: dict = None) -> str:
    notas = notas or {}
    out = ""
    for s in rows:
        did = quando(s["concluido_em"]) if s["concluido_em"] else "—"
        cat = f'<span class="tag cat">{e(s["categoria"])}</span>' if s["categoria"] else ""
        nota_tag = f'<span class="tag nota">★ {s["nota"]}/5</span>' if s["nota"] else ""
        # o histórico não some ao concluir: fica acessível aqui
        minhas = notas.get(s["id"], [])
        hist = f'<div class="tools">{render_notas(s, minhas, ocultos)}</div>' if minhas else ""
        out += f"""
            <div class="done-item">
                <div class="done-row">
                    <span class="did mono">{did}</span>
                    <span class="txt"><s>{e(s['assunto'])}</s></span>
                    {cat}
                    {nota_tag}
                    <span class="who">{e(s['solicitante'])}</span>
                    <form class="inline" method="post">
                        <input type="hidden" name="action" value="reabrir">
                        <input type="hidden" name="id" value="{s['id']}">
                        {ocultos}
                        <button class="btn ghost" type="submit">Reabrir</button>
                    </form>
                </div>
                {render_share(s)}
                {hist}
            </div>"""
    return out


def render_abas(atual: str, por_fila: dict, n_alertas: int) -> str:
    abas = "".join(
        f'<a class="{"on" if k == atual else ""}" href="{v["path"]}">{v["rotulo"]}'
        f'<span class="pill">{por_fila.get(k, 0)}</span></a>'
        for k, v in FILAS.items()
    )
    pill = f'<span class="pill{" bad" if n_alertas else ""}">{n_alertas}</span>'
    abas += (
        f'<a class="{"on" if atual == PATH_ALERTAS else ""}" href="{PATH_ALERTAS}">'
        f"Alertas{pill}</a>"
    )
    abas += (
        f'<a class="{"on" if atual == PATH_PAINEL else ""}" href="{PATH_PAINEL}">Painel</a>'
    )
    return abas


# Único JS da aplicação: completa os links de avaliação e copia pra área de
# transferência. `execCommand` porque em http na rede local (sem TLS) o
# navegador bloqueia `navigator.clipboard`.
SCRIPT = """
for (const i of document.querySelectorAll(".share-url")) {
    i.value = location.origin + i.dataset.p;
}
function copiar(botao) {
    const campo = botao.parentNode.querySelector("input");
    campo.select();
    campo.setSelectionRange(0, 99999);
    try { document.execCommand("copy"); botao.textContent = "Copiado!"; }
    catch (err) { botao.textContent = "Copie manualmente"; }
}
"""


def shell(titulo: str, sub: str, contadores: str, abas: str, banner: str, corpo: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" type="image/png" href="{PATH_ICONE}">
<title>Fila de Suporte · {titulo}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
    <header class="top">
        <img class="brand-logo" src="{PATH_LOGO}" alt="SolicitaMais">
        {contadores}
    </header>
    <p class="sub">{sub}</p>

    <nav class="filas">{abas}</nav>
    {banner}
    {corpo}
</div>
<script>{SCRIPT}</script>
</body>
</html>"""


def shell_publico(titulo: str, corpo: str, h1: str = "Como foi o atendimento?") -> str:
    """Casca das telas públicas: sem abas, sem contadores, sem fila.

    Quem abre esses links é o solicitante — ele vê o próprio atendimento e nada
    mais do sistema.
    """
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<link rel="icon" type="image/png" href="{PATH_ICONE}">
<title>{titulo}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap pub">
    <header class="top">
        <img class="brand-logo" src="{PATH_LOGO}" alt="SolicitaMais">
        <h1>{h1}</h1>
    </header>
    {corpo}
</div>
<script>{SCRIPT}</script>
</body>
</html>"""
