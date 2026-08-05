"""Renderização desta tela.

As dependências do núcleo são configuradas pelo app.py para manter as views
independentes do servidor HTTP e evitar importações circulares.
"""


def configurar(dependencias: dict) -> None:
    globals().update(
        {nome: valor for nome, valor in dependencias.items() if not nome.startswith("__")}
    )


def render_abrir(fila_sel: str = "", erro: str = "", vals: dict = None) -> str:
    """Formulário público: a própria pessoa abre e cai direto na fila certa."""
    vals = vals or {}
    aviso = f'<div class="erro">{e(erro)}</div>' if erro else ""

    tipos = "".join(
        f"""
            <label>
                <input type="radio" name="fila" value="{nome}"
                       {"checked" if fila_sel == nome else ""} required>
                <span><b>{conf["publico_rot"]}</b><small>{conf["publico"]}</small></span>
            </label>"""
        for nome, conf in FILAS.items()
    )

    corpo = f"""
    <p class="sub">Conte o que você precisa. Isso entra direto na nossa fila e
       a equipe assume daqui.</p>
    {aviso}
    <form class="card" method="post" action="{PATH_ABRIR}">
        <h2>Do que você precisa?</h2>
        <div class="rate tipos">{tipos}</div>

        <label for="solicitante">Seu nome</label>
        <input id="solicitante" name="solicitante" required maxlength="120"
               value="{e(vals.get("solicitante", ""))}" placeholder="Como te chamamos">

        <label for="assunto">Assunto</label>
        <input id="assunto" name="assunto" required maxlength="160"
               value="{e(vals.get("assunto", ""))}" placeholder="Resuma em uma linha">

        <label for="descricao">Detalhes</label>
        <textarea id="descricao" name="descricao" maxlength="2000"
                  placeholder="Contexto, número do contrato, o que já tentou…">{e(vals.get("descricao", ""))}</textarea>

        <button class="btn primary" type="submit">Enviar solicitação</button>
    </form>"""
    return shell_publico("Abrir solicitação", corpo, "Abrir uma solicitação")


def render_confirmacao(token: str) -> tuple:
    """Recibo da abertura: número, posição na fila e previsão. (html, status)."""
    conn = get_db()
    try:
        s = conn.execute(
            "SELECT * FROM solicitacoes WHERE token = ?", (token,)
        ).fetchone() if token else None
        est = estimativa_suporte(conn, s["id"]) if s and s["fila"] == FILA_SUPORTE else None
    finally:
        conn.close()

    if s is None:
        return shell_publico(
            "Abrir solicitação",
            '<div class="empty">Não achamos essa solicitação. '
            f'<a href="{PATH_ABRIR}">Abrir uma nova</a>.</div>',
            "Abrir uma solicitação",
        ), 404

    conf = FILAS[s["fila"] if s["fila"] in FILAS else FILA_SUPORTE]
    dados = f"""<dl class="dados">
        <dt>Nº</dt><dd>#{s["id"]} · {conf["rotulo"]}</dd>
        <dt>Assunto</dt><dd>{e(s["assunto"])}</dd>
        <dt>Solicitante</dt><dd>{e(s["solicitante"])}</dd>
        <dt>Aberto em</dt><dd>{quando(s["criado_em"])}</dd>
    </dl>"""

    if s["fila"] == FILA_DEMANDAS:
        destaque = """
    <div class="hero-card">
        <div class="hero-num">✓</div>
        <div class="hero-lbl">demanda registrada</div>
    </div>"""
        expectativa = """
    <div class="card" style="margin-top:18px;">
        <h2>E agora?</h2>
        <p>Demanda não tem previsão automática: ela vai ser analisada pela equipe e
           a data de execução é combinada diretamente com você.</p>
    </div>"""
    else:
        pos = est["posicao"]
        destaque = f"""
    <div class="hero-card">
        <div class="hero-num">{pos}º</div>
        <div class="hero-lbl">na fila de atendimento{
            f" · de {est['total']} em aberto" if est["total"] > 1 else ""}</div>
    </div>"""
        itens = []
        if est["media"] is not None:
            itens.append(f'<dt>Tempo médio de conclusão</dt><dd>{fmt_dur(est["media"])}</dd>')
        if est["previsao"] is not None:
            itens.append(
                f'<dt>Previsão de atendimento</dt><dd>{quando_previsto(est["previsao"])}</dd>'
            )
        if itens:
            corpo_exp = (f'<dl class="dados">{"".join(itens)}</dl>'
                         '<p class="viz-sub">Estimativa a partir do ritmo real dos '
                         'últimos atendimentos — pode mudar conforme a fila anda.</p>')
        else:
            corpo_exp = ("<p>Ainda não temos histórico suficiente pra estimar uma data. "
                         "A fila anda por ordem de chegada.</p>")
        expectativa = f"""
    <div class="card" style="margin-top:18px;">
        <h2>O que esperar</h2>
        {corpo_exp}
    </div>"""

    corpo = f"""
    <div class="obrigado">Solicitação enviada com sucesso. Se surgir qualquer dúvida,
        a equipe entra em contato com você pra esclarecer antes de resolver.</div>
    {destaque}
    <div class="card" style="margin-top:18px;">{dados}</div>
    {expectativa}
    <div class="card" style="margin-top:18px;">
        <h2>Acompanhe</h2>
        <p class="viz-sub">Guarde este link: ele mostra o andamento e, no fim,
           é por onde você avalia o atendimento.</p>
        <div class="share-box" style="padding-left:0;">
            <input class="share-url" data-p="{PATH_AVALIAR}?t={e(s["token"])}" readonly
                   value="{PATH_AVALIAR}?t={e(s["token"])}" onclick="this.select()"
                   aria-label="Link de acompanhamento">
            <button class="btn ghost" type="button" onclick="copiar(this)">Copiar</button>
        </div>
    </div>
    <p class="sub" style="margin-top:20px;">
        <a href="{PATH_ABRIR}">Abrir outra solicitação</a>
    </p>"""
    return shell_publico("Solicitação enviada", corpo, "Recebemos sua solicitação"), 200
