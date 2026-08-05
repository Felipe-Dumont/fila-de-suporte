"""Renderização desta tela.

As dependências do núcleo são configuradas pelo app.py para manter as views
independentes do servidor HTTP e evitar importações circulares.
"""


def configurar(dependencias: dict) -> None:
    globals().update(
        {nome: valor for nome, valor in dependencias.items() if not nome.startswith("__")}
    )


def renderizar(fila: str, f: dict) -> str:
    conf = FILAS[fila]
    conn = get_db()
    try:
        cond, cond_args = _condicoes(f)

        # posição real na fila: vem sempre da lista inteira, nunca da filtrada
        posicoes = {
            row["id"]: i + 1
            for i, row in enumerate(
                conn.execute(
                    "SELECT id FROM solicitacoes WHERE fila = ? AND status IN (?, ?) "
                    "ORDER BY criado_em ASC, id ASC",
                    (fila, STATUS_FILA, STATUS_ATENDIMENTO),
                )
            )
        }

        abertos = []
        if f["status"] != STATUS_CONCLUIDO:
            if f["status"]:
                where, args = ["fila = ?", "status = ?"], [fila, f["status"]]
            else:
                where = ["fila = ?", "status IN (?, ?)"]
                args = [fila, STATUS_FILA, STATUS_ATENDIMENTO]
            abertos = conn.execute(
                "SELECT * FROM solicitacoes WHERE " + " AND ".join(where + cond)
                + " ORDER BY criado_em ASC, id ASC",
                args + cond_args,
            ).fetchall()

        concluidos = []
        if f["status"] in ("", STATUS_CONCLUIDO):
            concluidos = conn.execute(
                "SELECT * FROM solicitacoes WHERE "
                + " AND ".join(["fila = ?", "status = ?"] + cond)
                + " ORDER BY concluido_em DESC, id DESC",
                [fila, STATUS_CONCLUIDO] + cond_args,
            ).fetchall()

        # contadores: totais reais da fila atual, independentes do filtro
        total_fila, total_atend = conn.execute(
            "SELECT COALESCE(SUM(status = ?), 0), COALESCE(SUM(status = ?), 0) "
            "FROM solicitacoes WHERE fila = ?",
            (STATUS_FILA, STATUS_ATENDIMENTO, fila),
        ).fetchone()

        # abertos por fila, pro contador das abas
        por_fila = dict(
            conn.execute(
                "SELECT fila, COUNT(*) FROM solicitacoes WHERE status IN (?, ?) "
                "GROUP BY fila",
                (STATUS_FILA, STATUS_ATENDIMENTO),
            ).fetchall()
        )

        # responsáveis já usados nesta fila, pro select e pro autocomplete
        devs = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT dev FROM solicitacoes WHERE fila = ? AND dev <> '' "
                "ORDER BY dev COLLATE NOCASE",
                (fila,),
            )
        ]

        # categorias já usadas nesta fila, pro filtro e pro autocomplete
        categorias = [
            r[0] for r in conn.execute(
                "SELECT DISTINCT categoria FROM solicitacoes WHERE fila = ? "
                "AND categoria <> '' ORDER BY categoria COLLATE NOCASE",
                (fila,),
            )
        ]

        notas = carregar_notas(conn, list(abertos) + list(concluidos))
        al = buscar_alertas(conn)
    finally:
        conn.close()

    ocultos = campos_ocultos(f, fila)
    rotulos = dict(FILTRO_STATUS)
    opcoes_datalist = "".join(f'<option value="{e(c)}">' for c in categorias)
    datalist = f'<datalist id="cats">{opcoes_datalist}</datalist>'
    datalist += '<datalist id="resps">' + "".join(
        f'<option value="{e(d)}">' for d in devs
    ) + "</datalist>"

    if f["status"] == STATUS_CONCLUIDO:
        queue_html = (
            render_concluidos(concluidos, ocultos, notas)
            if concluidos
            else '<div class="empty">Nada bate com esse filtro.</div>'
        )
        done_html = ""
    else:
        if abertos:
            queue_html = '<div class="queue">' + "".join(
                render_ticket(posicoes.get(s["id"], i + 1), s, ocultos, fila,
                              notas.get(s["id"], []))
                for i, s in enumerate(abertos)
            ) + "</div>"
        elif tem_filtro(f):
            queue_html = '<div class="empty">Nada bate com esse filtro.</div>'
        else:
            queue_html = f'<div class="empty">{conf["vazio"]}</div>'

        done_html = ""
        if concluidos:
            # com filtro ativo o accordion abre sozinho, senão o resultado ficaria escondido
            done_html = f"""
        <details class="done"{' open' if tem_filtro(f) else ''}>
            <summary>Concluídos ({len(concluidos)})</summary>
            <div style="margin-top:12px;">{render_concluidos(concluidos, ocultos, notas)}</div>
        </details>"""

    found_html = ""
    if tem_filtro(f):
        n = len(abertos) + len(concluidos)
        partes = []
        if f["q"]:
            partes.append(f'“{e(f["q"])}”')
        if f["status"]:
            partes.append(rotulos[f["status"]].lower())
        if f["prio"]:
            partes.append(f'prioridade {e(f["prio"])}')
        if f["resp"]:
            partes.append(
                conf["resp_sem"].lower() if f["resp"] == "—"
                else f'{conf["resp_filtro"]} {e(f["resp"])}'
            )
        if f["cat"]:
            partes.append("sem categoria" if f["cat"] == "—" else e(f["cat"]))
        found_html = (
            f'<p class="found"><b>{n}</b> resultado{"" if n == 1 else "s"} para '
            f'{" · ".join(partes)}<a href="{conf["path"]}">limpar filtro</a></p>'
        )

    opt_status = "".join(
        f'<option value="{v}"{" selected" if f["status"] == v else ""}>{rot}</option>'
        for v, rot in FILTRO_STATUS
    )
    opt_prio = '<option value="">Qualquer prioridade</option>' + "".join(
        f'<option value="{p}"{" selected" if f["prio"] == p else ""}>{p.capitalize()}</option>'
        for p in PRIORIDADES
    )

    # select de categoria só aparece depois que existe alguma cadastrada
    filtro_cat = ""
    if categorias:
        opts = '<option value="">Qualquer categoria</option>'
        opts += f'<option value="—"{" selected" if f["cat"] == "—" else ""}>Sem categoria</option>'
        opts += "".join(
            f'<option value="{e(c)}"{" selected" if f["cat"] == c else ""}>{e(c)}</option>'
            for c in categorias
        )
        filtro_cat = f'<select name="cat" onchange="this.form.submit()">{opts}</select>'

    # select de responsável só aparece depois que existe algum cadastrado na fila
    filtro_dev = ""
    if devs:
        opts = f'<option value="">{conf["resp_qualquer"]}</option>'
        opts += (f'<option value="—"{" selected" if f["resp"] == "—" else ""}>'
                 f'{conf["resp_sem"]}</option>')
        opts += "".join(
            f'<option value="{e(d)}"{" selected" if f["resp"] == d else ""}>{e(d)}</option>'
            for d in devs
        )
        filtro_dev = f'<select name="resp" onchange="this.form.submit()">{opts}</select>'

    titulo_secao = rotulos[f["status"]] if f["status"] else conf["secao"]

    abas = render_abas(fila, por_fila, al["total"])

    # responsável nas duas filas; previsão de entrega só nas demandas
    campos_extras = f"""
            <label for="dev">{conf['resp']}</label>
            <input id="dev" name="dev" maxlength="80" list="resps"
                   placeholder="Deixe vazio se ainda não definiu">"""
    if fila == FILA_DEMANDAS:
        campos_extras += """
            <label for="previsao">Previsão de entrega</label>
            <input id="previsao" name="previsao" type="date">"""

    corpo = f"""
    <div class="layout">
        <form class="card new" method="post">
            <h2>{conf['novo']}</h2>
            <input type="hidden" name="action" value="criar">
            {ocultos}
            <label for="solicitante">Solicitante</label>
            <input id="solicitante" name="solicitante" required maxlength="120" placeholder="Quem está pedindo">
            <label for="assunto">Assunto</label>
            <input id="assunto" name="assunto" required maxlength="160" placeholder="Resumo do problema">
            <label for="descricao">Detalhes</label>
            <textarea id="descricao" name="descricao" maxlength="2000" placeholder="Contexto, passos, o que já foi tentado…"></textarea>
            <label for="categoria">Categoria</label>
            <input id="categoria" name="categoria" maxlength="60" list="cats"
                   placeholder="Ex.: Contratos, Equipamento">
            <label for="prioridade">Prioridade</label>
            <select id="prioridade" name="prioridade">
                <option value="normal" selected>Normal</option>
                <option value="baixa">Baixa</option>
                <option value="alta">Alta</option>
            </select>{campos_extras}
            <button class="btn primary" type="submit">{conf['add']}</button>
            <div class="convite">
                <p>Link pro pessoal abrir sozinho — cai direto na fila:</p>
                <div class="share-box">
                    <input class="share-url" data-p="{PATH_ABRIR}" readonly
                           value="{PATH_ABRIR}" onclick="this.select()"
                           aria-label="Link público de abertura">
                    <button class="btn ghost" type="button" onclick="copiar(this)">Copiar</button>
                </div>
            </div>
        </form>

        <section>
            <h2 class="section">{titulo_secao}</h2>
            <form class="filters" method="get" action="{conf['path']}">
                <input type="search" name="q" value="{e(f['q'])}" maxlength="120"
                       placeholder="Buscar por solicitante, assunto ou detalhes…">
                <select name="status" onchange="this.form.submit()">{opt_status}</select>
                {filtro_cat}
                <select name="prio" onchange="this.form.submit()">{opt_prio}</select>
                {filtro_dev}
                <button class="btn ghost" type="submit">Filtrar</button>
            </form>
            {found_html}
            {queue_html}
            {done_html}
        </section>
    </div>
    {datalist}"""

    return shell(
        conf["rotulo"],
        conf["sub"],
        f'<div class="counts"><b>{total_fila}</b> aguardando · '
        f"<b>{total_atend}</b> em andamento</div>",
        abas,
        render_banner(al, aqui=False),
        corpo,
    )
