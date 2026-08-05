"""Renderização desta tela.

As dependências do núcleo são configuradas pelo app.py para manter as views
independentes do servidor HTTP e evitar importações circulares.
"""


def configurar(dependencias: dict) -> None:
    globals().update(
        {nome: valor for nome, valor in dependencias.items() if not nome.startswith("__")}
    )


def render_alertas() -> str:
    """Tela única com o que precisa de atenção nas duas filas."""
    conn = get_db()
    try:
        al = buscar_alertas(conn)
        por_fila = dict(
            conn.execute(
                "SELECT fila, COUNT(*) FROM solicitacoes WHERE status IN (?, ?) "
                "GROUP BY fila",
                (STATUS_FILA, STATUS_ATENDIMENTO),
            ).fetchall()
        )
        # posição real de cada item na sua fila de origem
        posicoes = {}
        for nome in FILAS:
            posicoes[nome] = {
                row["id"]: i + 1
                for i, row in enumerate(
                    conn.execute(
                        "SELECT id FROM solicitacoes WHERE fila = ? AND status IN (?, ?) "
                        "ORDER BY criado_em ASC, id ASC",
                        (nome, STATUS_FILA, STATUS_ATENDIMENTO),
                    )
                )
            }
        notas = carregar_notas(conn, list(al["espera"]) + list(al["prazo"]))
        categorias = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT categoria FROM solicitacoes WHERE categoria <> '' "
                "ORDER BY categoria COLLATE NOCASE"
            )
        ]
        # a tela mistura as duas filas, então o autocomplete junta todo mundo
        responsaveis = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT dev FROM solicitacoes WHERE dev <> '' "
                "ORDER BY dev COLLATE NOCASE"
            )
        ]
    finally:
        conn.close()

    vazio = {"q": "", "status": "", "prio": "", "resp": "", "cat": ""}

    def grupo(titulo: str, hint: str, rows, fila: str) -> str:
        if not rows:
            return ""
        ocultos = campos_ocultos(vazio, fila, voltar=PATH_ALERTAS)
        cards = "".join(
            render_ticket(posicoes[fila].get(s["id"], 0), s, ocultos, fila,
                          notas.get(s["id"], []))
            for s in rows
        )
        return f"""
        <div class="grupo">
            <h2 class="section">{titulo} <span class="badge">{len(rows)}</span></h2>
            <p class="hint">{hint}</p>
            <div class="queue">{cards}</div>
        </div>"""

    if al["total"]:
        corpo = grupo(
            "Suporte parado na fila",
            f"Entrou há mais de {LIMITE_ESPERA_HORAS}h e ninguém iniciou o atendimento.",
            al["espera"],
            FILA_SUPORTE,
        ) + grupo(
            "Demandas que venceram a previsão",
            "Chegou o dia previsto de entrega e a demanda ainda não foi iniciada.",
            al["prazo"],
            FILA_DEMANDAS,
        )
    else:
        corpo = (
            '<div class="empty">Nada pedindo atenção. '
            f"Nenhum suporte parado há {LIMITE_ESPERA_HORAS}h e nenhuma demanda vencida. 🎉"
            "</div>"
        )

    opcoes_datalist = "".join(f'<option value="{e(c)}">' for c in categorias)
    corpo += f'<datalist id="cats">{opcoes_datalist}</datalist>'
    corpo += '<datalist id="resps">' + "".join(
        f'<option value="{e(d)}">' for d in responsaveis
    ) + "</datalist>"

    return shell(
        "Alertas",
        "O que passou do ponto nas duas filas. Agir aqui já resolve na fila de origem.",
        f'<div class="counts"><b>{al["total"]}</b> pedindo atenção</div>',
        render_abas(PATH_ALERTAS, por_fila, al["total"]),
        render_banner(al, aqui=True),
        corpo,
    )
