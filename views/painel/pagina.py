"""Renderização e métricas da tela de painel."""

import sqlite3


def configurar(dependencias: dict) -> None:
    globals().update(
        {nome: valor for nome, valor in dependencias.items() if not nome.startswith("__")}
    )


def serie_temporal(concluidos, dias_periodo: int, data_especifica=None):
    """(rótulos, série suporte, série demandas). Vira semanal em período longo."""
    hoje = data_especifica or datetime.now(LOCAL_TZ).date()
    dia_de = {}
    for s in concluidos:
        d = _parse_utc(s["concluido_em"]).astimezone(LOCAL_TZ).date()
        dia_de.setdefault(d, []).append(s)

    if dias_periodo and dias_periodo <= 30:
        dias = [hoje - timedelta(days=i) for i in range(dias_periodo - 1, -1, -1)]
        chaves = [(d, d.strftime("%d/%m"), d.strftime("%d/%m/%Y"), [d]) for d in dias]
    else:
        # semanal: 13 semanas cheias, cada barra é a semana terminando naquele dia
        semanas = 13 if dias_periodo else 26
        chaves = []
        for i in range(semanas - 1, -1, -1):
            fim = hoje - timedelta(days=7 * i)
            faixa = [fim - timedelta(days=j) for j in range(7)]
            chaves.append((fim, fim.strftime("%d/%m"),
                           f"semana até {fim.strftime('%d/%m/%Y')}", faixa))

    rotulos, sup, dem = [], [], []
    for _, curto, completo, faixa in chaves:
        linhas = [s for d in faixa for s in dia_de.get(d, [])]
        rotulos.append((curto, completo))
        sup.append(sum(1 for s in linhas if s["fila"] == FILA_SUPORTE))
        dem.append(sum(1 for s in linhas if s["fila"] == FILA_DEMANDAS))
    return rotulos, sup, dem


def coletar_metricas(
    conn: sqlite3.Connection,
    dias_periodo: int,
    data_especifica=None,
) -> dict:
    agora = datetime.now(timezone.utc)
    hoje = datetime.now(LOCAL_TZ).date()

    extra, args = "", []
    if data_especifica:
        inicio_local = datetime(
            data_especifica.year,
            data_especifica.month,
            data_especifica.day,
            tzinfo=LOCAL_TZ,
        )
        fim_local = inicio_local + timedelta(days=1)
        extra = " AND concluido_em >= ? AND concluido_em < ?"
        args = [
            inicio_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            fim_local.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        ]
    elif dias_periodo:
        extra = " AND concluido_em >= ?"
        args = [(agora - timedelta(days=dias_periodo)).strftime("%Y-%m-%d %H:%M:%S")]
    concluidos = conn.execute(
        "SELECT * FROM solicitacoes WHERE status = ? AND concluido_em IS NOT NULL"
        + extra + " ORDER BY concluido_em DESC, id DESC",
        [STATUS_CONCLUIDO] + args,
    ).fetchall()
    abertos = conn.execute(
        "SELECT * FROM solicitacoes WHERE status IN (?, ?) ORDER BY criado_em ASC",
        (STATUS_FILA, STATUS_ATENDIMENTO),
    ).fetchall()

    # ---- o que foi feito
    duracoes = sorted(
        (_parse_utc(s["concluido_em"]) - _parse_utc(s["criado_em"])).total_seconds() / 60
        for s in concluidos
    )
    media = sum(duracoes) / len(duracoes) if duracoes else None
    mediana = duracoes[len(duracoes) // 2] if duracoes else None

    def conta(linhas, chave, vazio):
        acc = {}
        for s in linhas:
            acc[s[chave] or vazio] = acc.get(s[chave] or vazio, 0) + 1
        return sorted(acc.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    # ---- avaliações (opcionais: só uma parte dos concluídos tem nota)
    avaliadas = sorted(
        (s for s in concluidos if s["nota"]),
        key=lambda s: s["nota_em"] or "", reverse=True,
    )
    nota_media = sum(s["nota"] for s in avaliadas) / len(avaliadas) if avaliadas else None
    dist_notas = [
        (f"{n} · {rot}", sum(1 for s in avaliadas if s["nota"] == n)) for n, rot in NOTAS
    ]
    # média por solicitante: quem avaliou mais de uma vez conta a média das notas
    acc = {}
    for s in avaliadas:
        acc.setdefault(s["solicitante"], []).append(s["nota"])
    nota_por_pessoa = sorted(
        ((quem, round(sum(v) / len(v), 1)) for quem, v in acc.items()),
        key=lambda kv: (-kv[1], kv[0].lower()),
    )

    # ---- o que vem pela frente
    faixas =[("Menos de 2h", 0, 2 / 24), ("2h a 8h", 2 / 24, 8 / 24),
              ("8h a 1 dia", 8 / 24, 1), ("1 a 3 dias", 1, 3), ("Mais de 3 dias", 3, 1e9)]
    idades = []
    for rot, ini, fim in faixas:
        n = 0
        for s in abertos:
            d = (agora - _parse_utc(s["criado_em"])).total_seconds() / 86400
            if ini <= d < fim:
                n += 1
        idades.append((rot, n))

    demandas_abertas = [s for s in abertos if s["fila"] == FILA_DEMANDAS]
    agenda = []
    for i in range(14):
        d = hoje + timedelta(days=i)
        alvo = d.isoformat()
        n = sum(1 for s in demandas_abertas if s["previsao"] == alvo)
        rot = "hoje" if i == 0 else ("amanhã" if i == 1 else d.strftime("%d/%m"))
        agenda.append(((rot, d.strftime("%d/%m/%Y")), n))
    vencidas = sum(
        1 for s in demandas_abertas
        if s["previsao"] and s["previsao"] < hoje.isoformat()
    )
    sem_previsao = sum(1 for s in demandas_abertas if not s["previsao"])
    carga_dev = conta(demandas_abertas, "dev", "Sem dev")

    # Vazão e projeção. A janela é o período escolhido; em "Tudo" é o tempo
    # real de histórico. Menos de uma semana de janela não vira ritmo: 4 itens
    # fechados no mesmo dia dariam "28/semana", que é ruído, não tendência.
    if data_especifica:
        janela = 1.0
    elif dias_periodo:
        janela = float(dias_periodo)
    elif concluidos:
        inicio = min(_parse_utc(s["criado_em"]) for s in concluidos)
        janela = max(1.0, (agora - inicio).total_seconds() / 86400)
    else:
        janela = 1.0
    vazao = len(concluidos) / janela
    confiavel = janela >= 7 and len(concluidos) >= 3
    projecao = len(abertos) / vazao if confiavel and vazao > 0 else None

    mais_antigo = abertos[0] if abertos else None

    return {
        "concluidos": concluidos, "abertos": abertos,
        "media": media, "mediana": mediana,
        "por_categoria": conta(concluidos, "categoria", "Sem categoria"),
        "por_solicitante": conta(concluidos, "solicitante", "—"),
        "avaliadas": avaliadas, "nota_media": nota_media, "dist_notas": dist_notas,
        "nota_por_pessoa": nota_por_pessoa,
        "idades": idades, "agenda": agenda, "vencidas": vencidas,
        "sem_previsao": sem_previsao, "carga_dev": carga_dev,
        "vazao": vazao, "projecao": projecao, "confiavel": confiavel,
        "janela": janela, "mais_antigo": mais_antigo,
        "serie": serie_temporal(
            concluidos,
            1 if data_especifica else dias_periodo,
            data_especifica,
        ),
    }


def render_painel(
    dias_periodo: int,
    data_especifica=None,
    pessoa_selecionada: str = "",
) -> str:
    conn = get_db()
    try:
        m = coletar_metricas(conn, dias_periodo, data_especifica)
        al = buscar_alertas(conn)
        por_fila = dict(
            conn.execute(
                "SELECT fila, COUNT(*) FROM solicitacoes WHERE status IN (?, ?) GROUP BY fila",
                (STATUS_FILA, STATUS_ATENDIMENTO),
            ).fetchall()
        )
        responsaveis = [
            row[0] for row in conn.execute(
                "SELECT DISTINCT dev FROM solicitacoes WHERE dev <> '' "
                "ORDER BY dev COLLATE NOCASE"
            )
        ]
    finally:
        conn.close()

    pessoa_selecionada = (
        pessoa_selecionada if pessoa_selecionada in responsaveis else ""
    )
    rot_periodo = dict(PERIODOS)[dias_periodo]
    rotulo_periodo = (
        data_especifica.strftime("dia %d/%m/%Y")
        if data_especifica else (
            "todo o histórico" if not dias_periodo
            else "últimos " + rot_periodo.lower()
        )
    )
    n_concl = len(m["concluidos"])
    n_abertos = len(m["abertos"])

    def tile(rotulo, valor, nota=""):
        nota = f'<div class="nota">{nota}</div>' if nota else ""
        return f"""<div class="tile"><div class="rot">{rotulo}</div>
            <div class="val">{valor}</div>{nota}</div>"""

    # ---------- etapa 1: feito ----------
    rotulos, sup, dem = m["serie"]
    granularidade = (
        "no dia" if data_especifica
        else ("por dia" if dias_periodo and dias_periodo <= 30 else "por semana")
    )
    graf_tempo = svg_colunas(rotulos, [sup, dem], [COR_SUPORTE, COR_DEMANDAS],
                             ["Suporte", "Demandas"])
    tab_tempo = tabela_viz(
        ["Período", "Suporte", "Demandas", "Total"],
        [(c[1], s, d, s + d) for c, s, d in zip(rotulos, sup, dem) if s or d]
        or [("—", 0, 0, 0)],
    )

    graf_cat = svg_barras_h(m["por_categoria"][:8], largura=330)
    tab_cat = tabela_viz(["Categoria", "Concluídos"], m["por_categoria"] or [("—", 0)])
    graf_quem = svg_barras_h(m["por_solicitante"][:8], largura=330)
    tab_quem = tabela_viz(["Solicitante", "Concluídos"], m["por_solicitante"] or [("—", 0)])

    # avaliações seguem a paleta institucional, separada da escala de atraso
    n_aval = len(m["avaliadas"])
    graf_notas = svg_barras_h(m["dist_notas"], cores=list(reversed(RAMPA_AVALIACAO)),
                              largura=330)
    tab_notas = tabela_viz(["Nota", "Avaliações"], m["dist_notas"])
    graf_pessoa = svg_barras_h(m["nota_por_pessoa"][:8], largura=330)
    tab_pessoa = tabela_viz(["Solicitante", "Nota média"],
                            m["nota_por_pessoa"] or [("—", 0)])

    if n_aval:
        cobertura = f"{n_aval} de {n_concl} concluídos avaliados"
        nota_txt = f'{m["nota_media"]:.1f}/5'.replace(".", ",")
    else:
        cobertura = "ninguém avaliou no período"
        nota_txt = "—"

    linhas_aval = "".join(
        f"""<tr><td class="mono">{quando(s["nota_em"])}</td>
            <td>{e(s["solicitante"])}</td>
            <td>#{s["id"]} {e(s["assunto"][:44])}</td>
            <td><b>{s["nota"]}</b>/5</td>
            <td>{e(s["nota_obs"]) or "—"}</td></tr>"""
        for s in m["avaliadas"][:15]
    )
    detalhe_aval = (
        '<table class="tab" style="margin-top:14px;"><thead><tr>'
        "<th>Quando</th><th>Solicitante</th><th>Item</th><th>Nota</th>"
        "<th>Observação</th></tr></thead>"
        f"<tbody>{linhas_aval}</tbody></table>"
        if linhas_aval else ""
    )

    if m["confiavel"]:
        vazao_txt = f"{m['vazao'] * 7:.1f}/semana".replace(".0/", "/")
        vazao_nota = "ritmo médio de conclusão"
    else:
        vazao_txt = "—"
        vazao_nota = "menos de uma semana de histórico para medir ritmo"

    feito = f"""
    <section class="etapa">
        <div class="etapa-cab">
            <span class="passo">Etapa 1</span>
            <h2>O que foi feito</h2>
            <p>Retrospectiva do que saiu da fila. Tudo abaixo respeita o período escolhido.</p>
        </div>

        <div class="painel-filtros-periodo">
        <form class="periodos" method="get" action="{PATH_PAINEL}">
            {f'<input type="hidden" name="pessoa" value="{e(pessoa_selecionada)}">'
             if pessoa_selecionada else ""}
            {"".join(
                f'<button class="chip{" on" if not data_especifica and d == dias_periodo else ""}" '
                f'name="dias" value="{d}" type="submit">{r}</button>'
                for d, r in PERIODOS)}
        </form>
        <form class="data-painel" method="get" action="{PATH_PAINEL}">
            {f'<input type="hidden" name="pessoa" value="{e(pessoa_selecionada)}">'
             if pessoa_selecionada else ""}
            <label for="painel-data">Dia específico</label>
            <input id="painel-data" name="data" type="date"
                   value="{data_especifica.isoformat() if data_especifica else ''}"
                   max="{datetime.now(LOCAL_TZ).date().isoformat()}">
            <button class="btn ghost" type="submit">Aplicar</button>
        </form>
        </div>

        <div class="hero-card">
            <div class="hero-num">{n_concl}</div>
            <div class="hero-lbl">concluídos · {rotulo_periodo}</div>
        </div>

        <div class="kpis">
            {tile("Tempo médio até concluir", fmt_dur(m["media"]),
                  "da abertura até a conclusão")}
            {tile("Mediana", fmt_dur(m["mediana"]), "menos sensível a caso extremo")}
            {tile("Vazão", vazao_txt, vazao_nota)}
            {tile("Nota média", nota_txt, cobertura)}
        </div>

        <div class="viz-card">
            <h3>Conclusões ao longo do tempo</h3>
            <p class="viz-sub">Empilhado {granularidade}, separando as duas filas.</p>
            {legenda([("Suporte", COR_SUPORTE), ("Demandas", COR_DEMANDAS)])}
            {graf_tempo}
            {tab_tempo}
        </div>

        <div class="viz-dupla">
            <div class="viz-card">
                <h3>Por categoria</h3>
                <p class="viz-sub">Onde o trabalho concluído se concentra.</p>
                {graf_cat}
                {tab_cat}
            </div>
            <div class="viz-card">
                <h3>Quem mais pediu</h3>
                <p class="viz-sub">Solicitantes com mais itens concluídos.</p>
                {graf_quem}
                {tab_quem}
            </div>
        </div>

        <div class="viz-dupla">
            <div class="viz-card">
                <h3>Notas recebidas</h3>
                <p class="viz-sub">Distribuição das avaliações. Avaliar é opcional,
                   então isso cobre {cobertura}.</p>
                {graf_notas}
                {tab_notas}
            </div>
            <div class="viz-card">
                <h3>Nota média por solicitante</h3>
                <p class="viz-sub">Média das notas que cada pessoa deu.</p>
                {graf_pessoa}
                {tab_pessoa}
            </div>
        </div>

        <div class="viz-card">
            <h3>Avaliação de cada atendimento</h3>
            <p class="viz-sub">{"A avaliação mais recente" if n_aval == 1
               else f"As {min(n_aval, 15)} avaliações mais recentes"}, com o que
               o solicitante escreveu.</p>
            {detalhe_aval or _sem_dados("Nenhuma avaliação recebida no período.")}
        </div>
    </section>"""

    # ---------- etapa 2: previsão ----------
    graf_idade = svg_barras_h(m["idades"], cores=list(RAMPA_ATRASO))
    tab_idade = tabela_viz(["Faixa de espera", "Abertos"], m["idades"])

    ag_rot = [r for r, _ in m["agenda"]]
    ag_val = [v for _, v in m["agenda"]]
    graf_agenda = (svg_colunas(ag_rot, [ag_val], [COR_DEMANDAS], ["Demandas"], largura=330)
                   if sum(ag_val) else _sem_dados("Nenhuma demanda com previsão nos próximos 14 dias."))
    tab_agenda = tabela_viz(["Dia", "Demandas previstas"],
                            [(r[1], v) for r, v in m["agenda"] if v] or [("—", 0)])

    graf_carga = svg_barras_h(m["carga_dev"][:8], cores=[COR_DEMANDAS] * 8, largura=330)
    tab_carga = tabela_viz(["Dev", "Demandas abertas"], m["carga_dev"] or [("—", 0)])

    if m["projecao"] is None:
        proj_val, proj_nota = "—", "histórico curto demais para projetar"
    else:
        proj_val = fmt_dur(m["projecao"] * 24 * 60)
        alvo = (datetime.now(LOCAL_TZ).date()
                + timedelta(days=round(m["projecao"]))).strftime("%d/%m")
        proj_nota = f"no ritmo atual, fila zerada por volta de {alvo}"

    antigo = m["mais_antigo"]
    antigo_val = duracao(antigo["criado_em"]) if antigo else "—"
    antigo_nota = (f'#{antigo["id"]} · {e(antigo["assunto"][:38])}' if antigo
                   else "fila vazia")

    previsao = f"""
    <section class="etapa">
        <div class="etapa-cab">
            <span class="passo">Etapa 2</span>
            <h2>O que vem pela frente</h2>
            <p>Foto do agora e projeção. Esta parte ignora o período — olha só o que está aberto.</p>
        </div>

        <div class="kpis">
            {tile("Abertos agora", n_abertos, "nas duas filas somadas")}
            {tile("Projeção para zerar", proj_val, proj_nota)}
            {tile("Espera mais longa", antigo_val, antigo_nota)}
            {tile("Demandas vencidas", m["vencidas"],
                  f'{m["sem_previsao"]} sem previsão definida')}
        </div>

        <div class="viz-card">
            <h3>Envelhecimento da fila</h3>
            <p class="viz-sub">Há quanto tempo cada item aberto está esperando.
               Azul indica acompanhamento, âmbar pede atenção e vermelho marca
               atraso crítico.</p>
            {legenda([
                ("Acompanhamento", RAMPA_ATRASO[1]),
                ("Atenção", RAMPA_ATRASO[2]),
                ("Crítico", RAMPA_ATRASO[4]),
            ])}
            {graf_idade}
            {tab_idade}
        </div>

        <div class="viz-dupla">
            <div class="viz-card">
                <h3>Agenda das demandas</h3>
                <p class="viz-sub">Entregas previstas nos próximos 14 dias.</p>
                {graf_agenda}
                {tab_agenda}
            </div>
            <div class="viz-card">
                <h3>Carga por dev</h3>
                <p class="viz-sub">Demandas abertas na mão de cada um.</p>
                {graf_carga}
                {tab_carga}
            </div>
        </div>
    </section>"""

    # ---------- etapa 3: visão individual ----------
    opcoes_pessoa = '<option value="">Selecione um responsável</option>' + "".join(
        f'<option value="{e(nome)}"'
        f'{" selected" if nome == pessoa_selecionada else ""}>{e(nome)}</option>'
        for nome in responsaveis
    )
    filtro_periodo_individual = (
        f'<input type="hidden" name="data" value="{data_especifica.isoformat()}">'
        if data_especifica else f'<input type="hidden" name="dias" value="{dias_periodo}">'
    )

    if pessoa_selecionada:
        concluidos_pessoa = [
            chamado for chamado in m["concluidos"]
            if chamado["dev"] == pessoa_selecionada
        ]
        abertos_pessoa = [
            chamado for chamado in m["abertos"]
            if chamado["dev"] == pessoa_selecionada
        ]
        duracoes_pessoa = [
            (_parse_utc(chamado["concluido_em"]) - _parse_utc(chamado["criado_em"]))
            .total_seconds() / 60
            for chamado in concluidos_pessoa
        ]
        media_pessoa = (
            sum(duracoes_pessoa) / len(duracoes_pessoa) if duracoes_pessoa else None
        )
        avaliacoes_pessoa = [
            chamado["nota"] for chamado in concluidos_pessoa if chamado["nota"]
        ]
        nota_pessoa = (
            sum(avaliacoes_pessoa) / len(avaliacoes_pessoa)
            if avaliacoes_pessoa else None
        )
        suporte_pessoa = sum(
            1 for chamado in concluidos_pessoa if chamado["fila"] == FILA_SUPORTE
        )
        demandas_pessoa = len(concluidos_pessoa) - suporte_pessoa
        linhas_pessoa = "".join(
            f"""<tr>
                <td class="mono">{quando(chamado["concluido_em"])}</td>
                <td>#{chamado["id"]} {e(chamado["assunto"][:52])}</td>
                <td>{e(chamado["solicitante"])}</td>
                <td>{e(FILAS[chamado["fila"]]["rotulo"])}</td>
                <td>{fmt_dur(
                    (_parse_utc(chamado["concluido_em"]) - _parse_utc(chamado["criado_em"]))
                    .total_seconds() / 60
                )}</td>
                <td>{f'{chamado["nota"]}/5' if chamado["nota"] else "—"}</td>
            </tr>"""
            for chamado in concluidos_pessoa[:15]
        )
        detalhe_pessoa = f"""
            <div class="kpis">
                {tile("Concluídos", len(concluidos_pessoa), rotulo_periodo)}
                {tile("Abertos agora", len(abertos_pessoa), "atribuídos a esta pessoa")}
                {tile("Tempo médio", fmt_dur(media_pessoa), "da abertura à conclusão")}
                {tile(
                    "Nota média",
                    f'{nota_pessoa:.1f}/5'.replace('.', ',') if nota_pessoa else "—",
                    f'{len(avaliacoes_pessoa)} '
                    f'{"avaliação" if len(avaliacoes_pessoa) == 1 else "avaliações"}',
                )}
            </div>
            <div class="viz-card">
                <h3>Atendimentos de {e(pessoa_selecionada)}</h3>
                <p class="viz-sub">
                    {suporte_pessoa} de Suporte · {demandas_pessoa} de Demandas ·
                    exibindo até 15 conclusões mais recentes.
                </p>
                {('<table class="tab"><thead><tr><th>Concluído em</th><th>Chamado</th>'
                  '<th>Solicitante</th><th>Fila</th><th>Tempo</th><th>Nota</th></tr></thead>'
                  f'<tbody>{linhas_pessoa}</tbody></table>')
                 if linhas_pessoa else _sem_dados("Nenhum atendimento concluído no período.")}
            </div>
        """
    else:
        detalhe_pessoa = _sem_dados(
            "Selecione um responsável para consultar seus indicadores individuais."
        )

    individual = f"""
    <section class="etapa">
        <div class="etapa-cab">
            <span class="passo">Etapa 3</span>
            <h2>Visão individual</h2>
            <p>Indicadores do responsável selecionado dentro de {rotulo_periodo}.</p>
        </div>
        <form class="filtro-individual" method="get" action="{PATH_PAINEL}">
            {filtro_periodo_individual}
            <label for="painel-pessoa">Responsável</label>
            <select id="painel-pessoa" name="pessoa" onchange="this.form.requestSubmit()">
                {opcoes_pessoa}
            </select>
            <button class="btn ghost" type="submit">Consultar</button>
        </form>
        {detalhe_pessoa}
    </section>"""

    return shell(
        "Painel",
        "Duas etapas: o que já foi feito e o que vem pela frente.",
        f'<div class="counts"><b>{n_concl}</b> concluídos · <b>{n_abertos}</b> abertos</div>',
        render_abas(PATH_PAINEL, por_fila, al["total"]),
        render_banner(al, aqui=False),
        feito + previsao + individual,
    )
