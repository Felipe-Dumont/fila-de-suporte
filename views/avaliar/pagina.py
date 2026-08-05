"""Renderização desta tela.

As dependências do núcleo são configuradas pelo app.py para manter as views
independentes do servidor HTTP e evitar importações circulares.
"""


def configurar(dependencias: dict) -> None:
    globals().update(
        {nome: valor for nome, valor in dependencias.items() if not nome.startswith("__")}
    )


def render_andamento(notas) -> str:
    """Linha do tempo que o solicitante vê: só as anotações marcadas como públicas."""
    if not notas:
        return ""
    itens = "".join(
        f'<li><span class="qdo mono">{quando(n["criado_em"])}</span>'
        f'<p>{e(n["texto"])}</p></li>'
        for n in notas
    )
    return f"""
    <div class="card" style="margin-top:18px;">
        <h2>Andamento</h2>
        <ul class="andamento">{itens}</ul>
    </div>"""


def render_avaliacao(token: str, salvo: bool = False) -> tuple:
    """Página pública de avaliação. Devolve (html, status)."""
    conn = get_db()
    try:
        s = conn.execute(
            "SELECT * FROM solicitacoes WHERE token = ?", (token,)
        ).fetchone() if token else None
        # só as anotações marcadas como públicas saem daqui
        publicas = conn.execute(
            "SELECT * FROM anotacoes WHERE solicitacao_id = ? AND publica = 1 "
            "ORDER BY criado_em ASC, id ASC", (s["id"],)
        ).fetchall() if s else []
    finally:
        conn.close()

    if s is None:
        return shell_publico(
            "Avaliar atendimento",
            '<p class="sub">Link inválido ou expirado.</p>'
            '<div class="empty">Não achamos esse atendimento. '
            "Confira o link com quem te enviou.</div>",
        ), 404

    conf = FILAS[s["fila"] if s["fila"] in FILAS else FILA_SUPORTE]
    linhas = [
        ("Assunto", e(s["assunto"])),
        ("Nº", f'#{s["id"]} · {conf["rotulo"]}'),
        ("Solicitante", e(s["solicitante"])),
    ]
    if s["categoria"]:
        linhas.append(("Categoria", e(s["categoria"])))
    if s["dev"]:
        linhas.append((conf["resp"], e(s["dev"])))
    linhas.append(("Aberto em", quando(s["criado_em"])))
    if s["concluido_em"]:
        gasto = (_parse_utc(s["concluido_em"]) - _parse_utc(s["criado_em"])).total_seconds() / 60
        linhas.append(("Concluído em", quando(s["concluido_em"])))
        linhas.append(("Tempo até concluir", fmt_dur(gasto)))
    if s["descricao"]:
        linhas.append(("Detalhes", e(s["descricao"])))

    dados = '<dl class="dados">' + "".join(
        f"<dt>{rot}</dt><dd>{val}</dd>" for rot, val in linhas
    ) + "</dl>"
    andamento = render_andamento(publicas)

    if s["status"] != STATUS_CONCLUIDO:
        corpo = f"""
    <p class="sub">Este atendimento ainda está em andamento.</p>
    <div class="card">{dados}</div>
    {andamento}
    <div class="empty" style="margin-top:18px;">A avaliação abre assim que
        o atendimento for concluído. Guarde este link.</div>"""
        return shell_publico(f'Acompanhar · {s["assunto"][:40]}', corpo,
                             "Acompanhe seu atendimento"), 200

    opcoes = "".join(
        f"""
            <label>
                <input type="radio" name="nota" value="{n}"
                       {"checked" if s["nota"] == n else ""} required>
                <span><b>{n}</b><small>{rot}</small></span>
            </label>"""
        for n, rot in NOTAS
    )

    if salvo:
        aviso = ('<div class="obrigado">Avaliação registrada. Obrigado! '
                 "Se quiser mudar algo, é só reenviar.</div>")
    elif s["nota"]:
        aviso = (f'<div class="obrigado">Você já avaliou este atendimento em '
                 f'{quando(s["nota_em"])}. Pode atualizar abaixo.</div>')
    else:
        aviso = ""

    corpo = f"""
    <p class="sub">Sua avaliação é opcional e leva dez segundos —
       ela ajuda a melhorar o atendimento.</p>
    {aviso}
    <div class="card">
        {dados}
    </div>
    {andamento}
    <form class="card" method="post" action="{PATH_AVALIAR}" style="margin-top:18px;">
        <input type="hidden" name="t" value="{e(s['token'])}">
        <h2>Sua nota</h2>
        <div class="rate">{opcoes}</div>
        <label for="obs">Observação (opcional)</label>
        <textarea id="obs" name="obs" maxlength="1000"
                  placeholder="O que funcionou bem, o que dá pra melhorar…">{e(s['nota_obs'])}</textarea>
        <button class="btn primary" type="submit">Enviar avaliação</button>
    </form>"""
    return shell_publico(f'Avaliar atendimento · {s["assunto"][:40]}', corpo), 200
