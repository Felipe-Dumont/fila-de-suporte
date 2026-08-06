"""Histórico unificado de chamados concluídos das duas filas."""


def configurar(dependencias: dict) -> None:
    globals().update(
        {nome: valor for nome, valor in dependencias.items() if not nome.startswith("__")}
    )


def render_concluidos_todos(params: dict | None = None) -> str:
    params = params or {}
    filtros = ler_filtros(params)
    fila = (params.get("fila", [""])[0] or "").strip()
    fila = fila if fila in FILAS else ""
    condicoes, argumentos = _condicoes(filtros)
    where = ["status = ?"] + condicoes
    argumentos = [STATUS_CONCLUIDO] + argumentos
    if fila:
        where.append("fila = ?")
        argumentos.append(fila)

    conn = get_db()
    try:
        chamados = conn.execute(
            "SELECT * FROM solicitacoes WHERE " + " AND ".join(where) + " "
            "ORDER BY concluido_em DESC, id DESC",
            argumentos,
        ).fetchall()
        total_concluidos = conn.execute(
            "SELECT COUNT(*) FROM solicitacoes WHERE status = ?",
            (STATUS_CONCLUIDO,),
        ).fetchone()[0]
        por_fila = dict(
            conn.execute(
                "SELECT fila, COUNT(*) FROM solicitacoes WHERE status IN (?, ?) "
                "GROUP BY fila",
                (STATUS_FILA, STATUS_ATENDIMENTO),
            ).fetchall()
        )
        responsaveis = [
            row[0] for row in conn.execute(
                "SELECT DISTINCT dev FROM solicitacoes WHERE status = ? AND dev <> '' "
                "ORDER BY dev COLLATE NOCASE",
                (STATUS_CONCLUIDO,),
            )
        ]
        categorias = [
            row[0] for row in conn.execute(
                "SELECT DISTINCT categoria FROM solicitacoes "
                "WHERE status = ? AND categoria <> '' ORDER BY categoria COLLATE NOCASE",
                (STATUS_CONCLUIDO,),
            )
        ]
        notas = carregar_notas(conn, chamados)
        alertas = buscar_alertas(conn)
    finally:
        conn.close()

    filtro_fila_oculto = (
        f'<input type="hidden" name="historico_fila" value="{e(fila)}">'
        if fila else ""
    )
    historico = "".join(
        render_concluidos(
            [chamado],
            campos_ocultos(
                filtros,
                chamado["fila"],
                voltar=PATH_CONCLUIDOS,
            ) + filtro_fila_oculto,
            notas,
            mostrar_fila=True,
        )
        for chamado in chamados
    )
    tem_filtros = tem_filtro(filtros) or bool(fila)
    vazio = (
        "Nenhum chamado corresponde aos filtros informados."
        if tem_filtros else "Nenhum chamado foi concluído até o momento."
    )
    opcoes_fila = '<option value="">Suporte e Demandas</option>' + "".join(
        f'<option value="{e(nome)}"{" selected" if fila == nome else ""}>'
        f'{e(configuracao["rotulo"])}</option>'
        for nome, configuracao in FILAS.items()
    )
    opcoes_responsavel = '<option value="">Qualquer responsável</option>'
    opcoes_responsavel += (
        f'<option value="—"{" selected" if filtros["resp"] == "—" else ""}>'
        "Sem responsável</option>"
    )
    opcoes_responsavel += "".join(
        f'<option value="{e(nome)}"{" selected" if filtros["resp"] == nome else ""}>'
        f'{e(nome)}</option>'
        for nome in responsaveis
    )
    opcoes_categoria = '<option value="">Qualquer categoria</option>'
    opcoes_categoria += (
        f'<option value="—"{" selected" if filtros["cat"] == "—" else ""}>'
        "Sem categoria</option>"
    )
    opcoes_categoria += "".join(
        f'<option value="{e(nome)}"{" selected" if filtros["cat"] == nome else ""}>'
        f'{e(nome)}</option>'
        for nome in categorias
    )
    opcoes_prioridade = '<option value="">Qualquer prioridade</option>' + "".join(
        f'<option value="{e(prioridade)}"'
        f'{" selected" if filtros["prio"] == prioridade else ""}>'
        f'{e(prioridade.capitalize())}</option>'
        for prioridade in PRIORIDADES
    )
    resultado = (
        f'<p class="found"><b>{len(chamados)}</b> resultado'
        f'{"" if len(chamados) == 1 else "s"}'
        f'<a href="{PATH_CONCLUIDOS}">limpar filtros</a></p>'
        if tem_filtros else ""
    )
    corpo = f"""
        <form class="filters" method="get" action="{PATH_CONCLUIDOS}">
            <input type="search" name="q" value="{e(filtros['q'])}" maxlength="120"
                   placeholder="Buscar por solicitante, assunto ou detalhes…">
            <select name="fila">{opcoes_fila}</select>
            <select name="resp">{opcoes_responsavel}</select>
            <select name="cat">{opcoes_categoria}</select>
            <select name="prio">{opcoes_prioridade}</select>
            <button class="btn ghost" type="submit">Filtrar</button>
        </form>
        {resultado}
        {historico or f'<div class="empty">{vazio}</div>'}
    """

    contador = f'<div class="counts"><b>{len(chamados)}</b> exibido'
    contador += "" if len(chamados) == 1 else "s"
    if tem_filtros:
        contador += f' · <b>{total_concluidos}</b> no histórico'
    contador += "</div>"

    return shell(
        "Concluídos",
        "Histórico completo de atendimentos finalizados em Suporte e Demandas.",
        contador,
        render_abas(PATH_CONCLUIDOS, por_fila, alertas["total"]),
        render_banner(alertas, aqui=False),
        f'<section><h2 class="section">Todos os concluídos</h2>{corpo}</section>',
    )
