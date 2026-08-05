#!/usr/bin/env python3
"""
Fila de Suporte — app de arquivo único (Python + SQLite).
Só usa a biblioteca padrão: nada de pip, nada de instalar. Rode com:

    python3 app.py            # abre em http://localhost:8000
    python3 app.py 8080       # ou escolha a porta

O banco (data.sqlite) é criado automaticamente ao lado deste arquivo.
"""

import html
import os
import secrets
import sqlite3
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlencode, urlparse

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:                       # sistema sem base de fusos: cai pro offset fixo
    LOCAL_TZ = timezone(timedelta(hours=-3))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.sqlite")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
# "0.0.0.0" = visível pra rede local; FILA_HOST=127.0.0.1 restringe a esta máquina
HOST = os.environ.get("FILA_HOST", "0.0.0.0")

STATUS_FILA = "na_fila"
STATUS_ATENDIMENTO = "em_atendimento"
STATUS_CONCLUIDO = "concluido"
PRIORIDADES = ("baixa", "normal", "alta")

# Alertas: quanto tempo uma solicitação de suporte pode ficar parada na fila
# antes de virar alerta. Demanda vira alerta quando chega o dia da previsão
# sem ninguém ter iniciado.
LIMITE_ESPERA_HORAS = 2
PATH_ALERTAS = "/alertas"
PATH_PAINEL = "/painel"

# Avaliação: página pública, aberta pelo link que o solicitante recebe. Nunca é
# obrigatória — item concluído sem nota continua normal em toda a aplicação.
PATH_AVALIAR = "/avaliar"
NOTAS = ((5, "Excelente"), (4, "Ótimo"), (3, "Bom"), (2, "Regular"), (1, "Ruim"))

# Abertura pelo próprio solicitante: outra tela pública, sem acesso à fila.
PATH_ABRIR = "/abrir"
# Janela em que a previsão pode cair. A vazão medida já é de tempo de relógio
# (inclui noite e fim de semana), então isto é só apresentação: nunca antecipa
# a estimativa, só empurra pra frente quando ela cairia de madrugada.
EXPEDIENTE = (8, 18)
DIAS_SEMANA = ("segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo")

# Paleta dos gráficos. Não escolhida no olho: validada com o validador da
# skill dataviz contra a superfície branca dos cards (#ffffff).
#   categórico 2 slots  -> ΔE CVD 24.7 / normal 33.6, contraste >= 3:1  (PASS)
#   rampa ordinal azul  -> L monotônica, ponta clara 2.11:1             (PASS)
COR_SUPORTE = "#2a78d6"     # slot categórico 1
COR_DEMANDAS = "#eb6834"    # slot categórico 2
RAMPA_IDADE = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b")
VIZ_GRID = "#e1e0d9"
VIZ_EIXO = "#c3c2b7"
VIZ_INK = "#52514e"
VIZ_MUTED = "#898781"

PERIODOS = ((7, "7 dias"), (30, "30 dias"), (90, "90 dias"), (0, "Tudo"))

# As duas filas moram na mesma tabela, separadas pela coluna `fila`.
FILA_SUPORTE = "suporte"
FILA_DEMANDAS = "demandas"
FILAS = {
    FILA_SUPORTE: {
        "rotulo": "Suporte",
        "path": "/",
        "sub": "Atendimento por ordem de chegada. O primeiro da fila é o próximo a ser resolvido.",
        "secao": "Na fila &amp; em atendimento",
        "novo": "Nova solicitação",
        "add": "Adicionar à fila",
        "vazio": "Nenhuma solicitação aberta. Fila zerada. 🎉",
        "iniciar": "Iniciar atendimento",
        "tag_espera": "Na fila",
        "tag_ativo": "Em atendimento",
        # rótulos da coluna `dev`, que nas duas filas guarda o responsável
        "resp": "Responsável",
        "resp_ph": "Quem vai atender",
        "resp_sem": "Sem responsável",
        "resp_qualquer": "Qualquer responsável",
        "resp_filtro": "responsável",
        "publico_rot": "Suporte",
        "publico": "Algo travou ou precisa ser resolvido agora",
    },
    FILA_DEMANDAS: {
        "rotulo": "Demandas",
        "path": "/demandas",
        "sub": "Demandas extras, fora do trabalho principal. Os devs puxam conforme sobra tempo.",
        "secao": "Abertas &amp; em andamento",
        "novo": "Nova demanda",
        "add": "Adicionar às demandas",
        "vazio": "Nenhuma demanda aberta.",
        "iniciar": "Iniciar demanda",
        "tag_espera": "Aberta",
        "tag_ativo": "Em andamento",
        "resp": "Dev responsável",
        "resp_ph": "Dev responsável",
        "resp_sem": "Sem dev",
        "resp_qualquer": "Qualquer dev",
        "resp_filtro": "dev",
        "publico_rot": "Demanda nova",
        "publico": "Um pedido novo, pra ser analisado e agendado",
    },
}

# rótulos do filtro de status; "" = tudo (abertos na lista, concluídos no accordion)
FILTRO_STATUS = (
    ("", "Todos"),
    (STATUS_FILA, "Na fila"),
    (STATUS_ATENDIMENTO, "Em atendimento"),
    (STATUS_CONCLUIDO, "Concluídos"),
)


# -----------------------------------------------------------------------------
# Banco de dados
# -----------------------------------------------------------------------------
def normalizar(texto: str) -> str:
    """minúsculas e sem acento, pra busca não depender de 'ç' nem de caixa."""
    decomposto = unicodedata.normalize("NFD", texto.lower())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def novo_token() -> str:
    """Chave do link de avaliação: opaca pra ninguém achar item alheio chutando id."""
    return secrets.token_urlsafe(9)


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL;")
    # o LIKE do SQLite só ignora caixa em ASCII e nunca ignora acento
    conn.create_function("norm", 1, lambda s: normalizar(s) if s else "")
    return conn


def init_db() -> None:
    conn = get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS solicitacoes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            solicitante  TEXT    NOT NULL,
            assunto      TEXT    NOT NULL,
            descricao    TEXT    NOT NULL DEFAULT '',
            prioridade   TEXT    NOT NULL DEFAULT 'normal',
            status       TEXT    NOT NULL DEFAULT 'na_fila',
            criado_em    TEXT    NOT NULL DEFAULT (datetime('now')),
            concluido_em TEXT
        )
        """
    )

    # migração idempotente: banco antigo só tinha a fila de suporte
    existentes = {c["name"] for c in conn.execute("PRAGMA table_info(solicitacoes)")}
    novas = (
        ("fila", f"TEXT NOT NULL DEFAULT '{FILA_SUPORTE}'"),
        ("dev", "TEXT NOT NULL DEFAULT ''"),       # responsável nas duas filas
        ("previsao", "TEXT"),                      # YYYY-MM-DD, só nas demandas
        ("categoria", "TEXT NOT NULL DEFAULT ''"),
        ("token", "TEXT"),                         # chave do link público de avaliação
        ("nota", "INTEGER"),                       # 1 a 5; NULL = ainda não avaliado
        ("nota_obs", "TEXT NOT NULL DEFAULT ''"),
        ("nota_em", "TEXT"),
    )
    for nome, ddl in novas:
        if nome not in existentes:
            conn.execute(f"ALTER TABLE solicitacoes ADD COLUMN {nome} {ddl}")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sol_token ON solicitacoes (token)"
    )
    # itens antigos não tinham token; sem isso não dá pra compartilhá-los
    faltando = [r["id"] for r in conn.execute(
        "SELECT id FROM solicitacoes WHERE token IS NULL OR token = ''"
    )]
    for sid in faltando:
        conn.execute("UPDATE solicitacoes SET token = ? WHERE id = ?", (novo_token(), sid))

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS anotacoes (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            solicitacao_id INTEGER NOT NULL,
            texto          TEXT    NOT NULL,
            criado_em      TEXT    NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_anotacoes_sol ON anotacoes (solicitacao_id)"
    )
    # anotação nasce privada: o que já existe era escrito sem ninguém de fora ler
    if "publica" not in {c["name"] for c in conn.execute("PRAGMA table_info(anotacoes)")}:
        conn.execute(
            "ALTER TABLE anotacoes ADD COLUMN publica INTEGER NOT NULL DEFAULT 0"
        )

    conn.commit()
    conn.close()


# -----------------------------------------------------------------------------
# Helpers de exibição
# -----------------------------------------------------------------------------
def e(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _parse_utc(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)


def quando(iso: str) -> str:
    return _parse_utc(iso).astimezone(LOCAL_TZ).strftime("%d/%m %H:%M")


def ler_data(v: str) -> str:
    """Aceita só YYYY-MM-DD (o que o <input type=date> manda). Inválido vira ''."""
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        return ""


def prazo(previsao: str) -> tuple:
    """(texto, classe da tag) para a previsão de entrega, relativo a hoje."""
    try:
        d = date.fromisoformat(previsao)
    except ValueError:
        return "", ""
    dias = (d - datetime.now(LOCAL_TZ).date()).days
    quando_txt = d.strftime("%d/%m")
    if dias < 0:
        atraso = -dias
        return f"Atrasada {atraso}d · era {quando_txt}", "late"
    if dias == 0:
        return f"Entrega hoje · {quando_txt}", "due"
    if dias == 1:
        return f"Entrega amanhã · {quando_txt}", "due"
    return f"Entrega {quando_txt} · em {dias}d", "plain"


def duracao(iso: str) -> str:
    """Tempo decorrido, curto: '45 min', '3h', '2d'."""
    mins = max(0, int((datetime.now(timezone.utc) - _parse_utc(iso)).total_seconds() // 60))
    if mins < 60:
        return f"{mins} min"
    horas = mins // 60
    return f"{horas}h" if horas < 24 else f"{horas // 24}d"


def esperando_desde(iso: str) -> str:
    if (datetime.now(timezone.utc) - _parse_utc(iso)).total_seconds() < 60:
        return "agora há pouco"
    return f"{duracao(iso)} na fila"


def proxima_janela(dt: datetime) -> datetime:
    """Empurra a data pra próxima hora de expediente, se cair fora dela."""
    ini, fim = EXPEDIENTE
    while True:
        if dt.weekday() >= 5:                      # sábado ou domingo
            dt = (dt + timedelta(days=1)).replace(hour=ini, minute=0)
            continue
        if dt.hour < ini:
            dt = dt.replace(hour=ini, minute=0)
        elif dt.hour >= fim:
            dt = (dt + timedelta(days=1)).replace(hour=ini, minute=0)
            continue
        return dt


def quando_previsto(dt: datetime) -> str:
    """Data da previsão em linguagem de gente: 'hoje', 'amanhã', 'quinta (01/08)'."""
    hoje = datetime.now(LOCAL_TZ).date()
    dias = (dt.date() - hoje).days
    if dias == 0:
        dia = "hoje"
    elif dias == 1:
        dia = "amanhã"
    elif dias < 7:
        dia = f'{DIAS_SEMANA[dt.weekday()]} ({dt.strftime("%d/%m")})'
    else:
        dia = dt.strftime("%d/%m/%Y")
    return f'{dia}, por volta das {dt.strftime("%Hh")}'


def estimativa_suporte(conn: sqlite3.Connection, sid: int) -> dict:
    """Posição na fila, tempo médio de conclusão e previsão pro item `sid`.

    A previsão sai da vazão real dos últimos 30 dias (itens por hora de
    relógio, já descontando noites e fins de semana). Com histórico curto
    demais pra medir ritmo, devolve previsão vazia — melhor não prometer.
    """
    fila = [r["id"] for r in conn.execute(
        "SELECT id FROM solicitacoes WHERE fila = ? AND status IN (?, ?) "
        "ORDER BY criado_em ASC, id ASC",
        (FILA_SUPORTE, STATUS_FILA, STATUS_ATENDIMENTO),
    )]
    pos = fila.index(sid) + 1 if sid in fila else 0

    agora = datetime.now(timezone.utc)
    def concluidos_desde(dias):
        corte = (agora - timedelta(days=dias)).strftime("%Y-%m-%d %H:%M:%S")
        return conn.execute(
            "SELECT criado_em, concluido_em FROM solicitacoes WHERE fila = ? "
            "AND status = ? AND concluido_em IS NOT NULL AND concluido_em >= ?",
            (FILA_SUPORTE, STATUS_CONCLUIDO, corte),
        ).fetchall()

    historico = concluidos_desde(90)
    media = None
    if historico:
        media = sum(
            (_parse_utc(r["concluido_em"]) - _parse_utc(r["criado_em"])).total_seconds() / 60
            for r in historico
        ) / len(historico)

    recentes = concluidos_desde(30)
    previsao = None
    if pos and len(recentes) >= 5:
        por_hora = len(recentes) / (30 * 24)
        previsao = proxima_janela(
            (agora + timedelta(hours=pos / por_hora)).astimezone(LOCAL_TZ)
        )
    return {"posicao": pos, "total": len(fila), "media": media, "previsao": previsao}


def canonizar(conn: sqlite3.Connection, coluna: str, valor: str) -> str:
    """Reaproveita a grafia já cadastrada quando o valor só difere em caixa/acento.

    Sem isso "Contratos", "contratos" e "Contrato " virariam três categorias
    distintas e os filtros e a contagem rachariam.
    """
    valor = valor.strip()
    if not valor:
        return ""
    for (existente,) in conn.execute(
        f"SELECT DISTINCT {coluna} FROM solicitacoes WHERE {coluna} <> ''"
    ):
        if normalizar(existente) == normalizar(valor):
            return existente
    return valor


def carregar_notas(conn: sqlite3.Connection, linhas) -> dict:
    """{id_da_solicitacao: [anotações]} para as linhas visíveis na tela."""
    ids = [s["id"] for s in linhas]
    if not ids:
        return {}
    marcadores = ",".join("?" * len(ids))
    notas = {}
    for r in conn.execute(
        f"SELECT * FROM anotacoes WHERE solicitacao_id IN ({marcadores}) "
        "ORDER BY criado_em ASC, id ASC",
        ids,
    ):
        notas.setdefault(r["solicitacao_id"], []).append(r)
    return notas


# -----------------------------------------------------------------------------
# Gráficos (SVG na mão — sem lib, sem CDN, o app continua offline)
# -----------------------------------------------------------------------------
GAP = 2          # respiro em cor de superfície entre marcas que se tocam
RAIO = 4         # ponta arredondada da barra; a base fica reta


def fmt_dur(mins) -> str:
    """Duração legível a partir de minutos."""
    if mins is None:
        return "—"
    mins = int(mins)
    if mins < 60:
        return f"{mins}min"
    if mins < 60 * 24:
        h = mins / 60
        return f"{h:.1f}h".replace(".0h", "h")
    d = mins / (60 * 24)
    return f"{d:.1f}d".replace(".0d", "d")


def _topo_redondo(x, y, w, h, cor, titulo) -> str:
    """Barra vertical: topo arredondado, base reta, ancorada na linha de base."""
    if h <= 0:
        return ""
    r = min(RAIO, w / 2, h)
    d = (f"M{x:.1f},{y + h:.1f} L{x:.1f},{y + r:.1f} Q{x:.1f},{y:.1f} {x + r:.1f},{y:.1f} "
         f"L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
         f"L{x + w:.1f},{y + h:.1f} Z")
    return f'<path d="{d}" fill="{cor}"><title>{e(titulo)}</title></path>'


def _ponta_redonda(x, y, w, h, cor, titulo) -> str:
    """Barra horizontal: ponta direita arredondada, base esquerda reta."""
    if w <= 0:
        return ""
    r = min(RAIO, h / 2, w)
    d = (f"M{x:.1f},{y:.1f} L{x + w - r:.1f},{y:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} "
         f"L{x + w:.1f},{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} "
         f"L{x:.1f},{y + h:.1f} Z")
    return f'<path d="{d}" fill="{cor}"><title>{e(titulo)}</title></path>'


def _sem_dados(msg: str) -> str:
    return f'<p class="viz-vazio">{e(msg)}</p>'


def _indices_rotulo(n: int, larg_util: float) -> set:
    """Quais rótulos do eixo X cabem sem encavalar, sempre incluindo o último."""
    cabem = max(2, int(larg_util / 38))
    passo = max(1, -(-n // cabem))
    mostrar = set(range(0, n, passo))
    mostrar.add(n - 1)
    # o último é obrigatório: se ficou colado no anterior, o anterior sai
    anteriores = [i for i in mostrar if i != n - 1]
    if anteriores and (n - 1) - max(anteriores) < passo:
        mostrar.discard(max(anteriores))
    return mostrar


def svg_colunas(dias, series, cores, rotulos, largura: int = 620) -> str:
    """Colunas (empilhadas quando há 2 séries) ao longo do tempo.

    dias: [(rótulo curto, rótulo completo)] · series: [[valores], ...]
    `largura` acompanha o espaço real do card: o SVG escala junto com a
    coluna, então um viewBox largo num card estreito encolheria o texto.
    """
    n = len(dias)
    if not n or not any(sum(s) for s in series):
        return _sem_dados("Nada concluído no período.")

    W, alt_plot, topo, base_lbl = largura, 148, 12, 30
    H = topo + alt_plot + base_lbl
    maximo = max(sum(col) for col in zip(*series)) or 1
    # ticks inteiros, e no máximo tantas divisões quanto o próprio valor:
    # com máximo 1 o eixo para em 1, em vez de deixar 3/4 do gráfico vazio
    divs = max(1, min(4, maximo))
    passo = -(-maximo // divs)
    teto = passo * divs

    partes = []
    for i in range(divs + 1):                            # grade recessiva, sólida
        y = topo + alt_plot - (alt_plot * i / divs)
        v = passo * i
        partes.append(
            f'<line x1="34" y1="{y:.1f}" x2="{W}" y2="{y:.1f}" stroke="{VIZ_GRID}" '
            'stroke-width="1"/>'
        )
        partes.append(
            f'<text x="28" y="{y + 3.5:.1f}" text-anchor="end" font-size="10" '
            f'fill="{VIZ_MUTED}" style="font-variant-numeric:tabular-nums">{v}</text>'
        )

    x0 = 34
    larg_util = W - x0
    banda = larg_util / n
    larg = min(24, banda * 0.62)
    mostrar_rotulo = _indices_rotulo(n, larg_util)
    for i, (curto, completo) in enumerate(dias):
        cx = x0 + banda * i + (banda - larg) / 2
        acc = 0.0
        pilha = [(s[i], cores[j], rotulos[j]) for j, s in enumerate(series) if s[i]]
        for k, (val, cor, rot) in enumerate(pilha):
            h = alt_plot * val / teto
            y = topo + alt_plot - acc - h
            topo_da_pilha = k == len(pilha) - 1
            # respiro de 2px entre segmentos que se tocam
            hh = h - (GAP if not topo_da_pilha else 0)
            titulo = f"{completo} · {rot}: {val}"
            if topo_da_pilha:
                partes.append(_topo_redondo(cx, y, larg, hh, cor, titulo))
            else:
                partes.append(
                    f'<rect x="{cx:.1f}" y="{y + GAP:.1f}" width="{larg:.1f}" '
                    f'height="{max(0, hh):.1f}" fill="{cor}"><title>{e(titulo)}</title></rect>'
                )
            acc += h
        total = sum(s[i] for s in series)
        if total:                                        # rótulo direto só no topo
            partes.append(
                f'<text x="{cx + larg / 2:.1f}" y="{topo + alt_plot - acc - 5:.1f}" '
                f'text-anchor="middle" font-size="10.5" fill="{VIZ_INK}" '
                f'font-weight="600">{total}</text>'
            )
        if i in mostrar_rotulo:
            partes.append(
                f'<text x="{cx + larg / 2:.1f}" y="{topo + alt_plot + 15:.1f}" '
                f'text-anchor="middle" font-size="10" fill="{VIZ_MUTED}">{e(curto)}</text>'
            )

    partes.append(
        f'<line x1="34" y1="{topo + alt_plot:.1f}" x2="{W}" y2="{topo + alt_plot:.1f}" '
        f'stroke="{VIZ_EIXO}" stroke-width="1"/>'
    )
    return (f'<svg class="viz" viewBox="0 0 {W} {H}" role="img" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(partes)}</svg>')


def svg_barras_h(itens, cores=None, sufixo="", largura: int = 620) -> str:
    """Barras horizontais para magnitude por categoria nominal.

    Uma cor só por padrão — barra mais longa já diz quem é maior, pintar por
    tamanho seria gastar o canal de cor com informação repetida.
    """
    if not itens:
        return _sem_dados("Sem dados para o período.")

    W, linha = largura, 30
    esq = min(132, largura * 0.36)
    H = linha * len(itens) + 6
    maximo = max(v for _, v in itens) or 1
    espesso = 16
    partes = []
    for i, (rot, val) in enumerate(itens):
        y = i * linha + 4
        cor = (cores[i] if cores else COR_SUPORTE)
        larg = (W - esq - 40) * val / maximo
        limite = max(10, int(esq / 6.6))
        curto = rot if len(rot) <= limite else rot[: limite - 1] + "…"
        partes.append(
            f'<text x="{esq - 10}" y="{y + espesso / 2 + 4:.1f}" text-anchor="end" '
            f'font-size="11.5" fill="{VIZ_INK}">{e(curto)}</text>'
        )
        partes.append(_ponta_redonda(esq, y, larg, espesso, cor, f"{rot}: {val}{sufixo}"))
        partes.append(
            f'<text x="{esq + larg + 8:.1f}" y="{y + espesso / 2 + 4:.1f}" font-size="11.5" '
            f'fill="{VIZ_INK}" font-weight="600" '
            f'style="font-variant-numeric:tabular-nums">{val}{e(sufixo)}</text>'
        )
    return (f'<svg class="viz" viewBox="0 0 {W} {H}" role="img" '
            f'preserveAspectRatio="xMidYMid meet">{"".join(partes)}</svg>')


def tabela_viz(cabecalho, linhas) -> str:
    """Gêmea em tabela de cada gráfico: nenhum valor fica preso no hover."""
    ths = "".join(f"<th>{e(c)}</th>" for c in cabecalho)
    trs = ""
    for ln in linhas:
        trs += "<tr>" + "".join(f"<td>{e(c)}</td>" for c in ln) + "</tr>"
    return f"""
        <details class="tool viz-tab">
            <summary>ver tabela</summary>
            <div class="painel">
                <table class="tab"><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>
            </div>
        </details>"""


def legenda(itens) -> str:
    """Identidade nunca só pela cor: swatch + texto em tinta normal."""
    return '<div class="viz-leg">' + "".join(
        f'<span><i style="background:{c}"></i>{e(r)}</span>' for r, c in itens
    ) + "</div>"


# -----------------------------------------------------------------------------
# Alertas
# -----------------------------------------------------------------------------
def espera_estourada(s: sqlite3.Row) -> bool:
    """Suporte parado na fila além do limite, sem ninguém ter iniciado."""
    if s["status"] != STATUS_FILA:
        return False
    idade = datetime.now(timezone.utc) - _parse_utc(s["criado_em"])
    return idade >= timedelta(hours=LIMITE_ESPERA_HORAS)


def prazo_vencido(s: sqlite3.Row) -> bool:
    """Demanda que chegou no dia da previsão (ou passou) sem ser iniciada."""
    if s["status"] != STATUS_FILA or not s["previsao"]:
        return False
    return s["previsao"] <= datetime.now(LOCAL_TZ).date().isoformat()


def em_alerta(s: sqlite3.Row, fila: str) -> bool:
    return espera_estourada(s) if fila == FILA_SUPORTE else prazo_vencido(s)


def buscar_alertas(conn: sqlite3.Connection) -> dict:
    """As duas listas de alerta, já filtradas no SQL."""
    corte = (
        datetime.now(timezone.utc) - timedelta(hours=LIMITE_ESPERA_HORAS)
    ).strftime("%Y-%m-%d %H:%M:%S")
    espera = conn.execute(
        "SELECT * FROM solicitacoes WHERE fila = ? AND status = ? AND criado_em <= ? "
        "ORDER BY criado_em ASC, id ASC",
        (FILA_SUPORTE, STATUS_FILA, corte),
    ).fetchall()
    prazo = conn.execute(
        "SELECT * FROM solicitacoes WHERE fila = ? AND status = ? "
        "AND previsao IS NOT NULL AND previsao <> '' AND previsao <= ? "
        "ORDER BY previsao ASC, id ASC",
        (FILA_DEMANDAS, STATUS_FILA, datetime.now(LOCAL_TZ).date().isoformat()),
    ).fetchall()
    return {"espera": espera, "prazo": prazo, "total": len(espera) + len(prazo)}


def render_banner(al: dict, aqui: bool) -> str:
    """Faixa de aviso no topo. `aqui` = já estamos na tela de alertas."""
    if not al["total"]:
        return ""
    partes = []
    if al["espera"]:
        n = len(al["espera"])
        partes.append(
            f'<b>{n}</b> {"solicitação parada" if n == 1 else "solicitações paradas"}'
            f" há mais de {LIMITE_ESPERA_HORAS}h"
        )
    if al["prazo"]:
        n = len(al["prazo"])
        partes.append(
            f'<b>{n}</b> {"demanda venceu" if n == 1 else "demandas venceram"}'
            " a previsão sem começar"
        )
    texto = " · ".join(partes)
    if aqui:
        return f'<div class="alerta">⚠ {texto}</div>'
    return f'<a class="alerta" href="{PATH_ALERTAS}">⚠ {texto} <span class="ver">ver →</span></a>'


# -----------------------------------------------------------------------------
# Filtros
# -----------------------------------------------------------------------------
def ler_filtros(params: dict) -> dict:
    """Lê q / status / prio / resp da query string, descartando valor inválido.

    `resp` filtra a coluna `dev`; o nome é diferente de propósito, pra não
    colidir com o campo `dev` dos formulários de criação e atribuição.
    """
    def g(k: str) -> str:
        return (params.get(k, [""])[0] or "").strip()

    status, prio = g("status"), g("prio")
    return {
        "q": g("q"),
        "status": status if status in dict(FILTRO_STATUS) else "",
        "prio": prio if prio in PRIORIDADES else "",
        "resp": g("resp"),
        "cat": g("cat"),
    }


def tem_filtro(f: dict) -> bool:
    return any(f.values())


def query_string(f: dict) -> str:
    ativos = {k: v for k, v in f.items() if v}
    return "?" + urlencode(ativos) if ativos else ""


def campos_ocultos(f: dict, fila: str, voltar: str = "") -> str:
    """Repassa fila + filtro nos forms de ação, pra não perdê-los no redirect.

    `voltar` força o destino do redirect (usado pela tela de alertas, que
    mistura as duas filas e não deve jogar você pra outra aba a cada clique).
    """
    campos = {"fila": fila, **{k: v for k, v in f.items() if v}}
    if voltar:
        campos["voltar"] = voltar
    return "".join(
        f'<input type="hidden" name="{k}" value="{e(v)}">' for k, v in campos.items()
    )


def _condicoes(f: dict) -> tuple:
    """Trechos de WHERE comuns às duas listas (texto livre e prioridade)."""
    cond, args = [], []
    if f["q"]:
        alvo = normalizar(f["q"]).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        cond.append(
            "(norm(solicitante) LIKE ? ESCAPE '\\'"
            " OR norm(assunto) LIKE ? ESCAPE '\\'"
            " OR norm(descricao) LIKE ? ESCAPE '\\')"
        )
        args += [f"%{alvo}%"] * 3
    if f["prio"]:
        cond.append("prioridade = ?")
        args.append(f["prio"])
    if f["resp"]:
        # "—" é a opção "sem dev definido" do select
        if f["resp"] == "—":
            cond.append("dev = ''")
        else:
            cond.append("dev = ?")
            args.append(f["resp"])
    if f["cat"]:
        if f["cat"] == "—":
            cond.append("categoria = ''")
        else:
            cond.append("categoria = ?")
            args.append(f["cat"])
    return cond, args


# -----------------------------------------------------------------------------
# Ações (POST)
# -----------------------------------------------------------------------------
def handle_action(form: dict) -> None:
    def g(k: str) -> str:
        return (form.get(k, [""])[0] or "").strip()

    action = g("action")
    fila = g("fila") if g("fila") in FILAS else FILA_SUPORTE
    conn = get_db()
    try:
        if action == "criar":
            solicitante, assunto = g("solicitante"), g("assunto")
            descricao = g("descricao")
            prioridade = g("prioridade") if g("prioridade") in PRIORIDADES else "normal"
            # responsável existe nas duas filas; previsão só nas demandas
            dev = g("dev")
            previsao = ler_data(g("previsao")) if fila == FILA_DEMANDAS else ""
            if solicitante and assunto:
                conn.execute(
                    "INSERT INTO solicitacoes "
                    "(solicitante, assunto, descricao, prioridade, fila, dev, "
                    "previsao, categoria, token) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (solicitante, assunto, descricao, prioridade, fila,
                     canonizar(conn, "dev", dev), previsao or None,
                     canonizar(conn, "categoria", g("categoria")), novo_token()),
                )

        elif action == "editar" and g("id").isdigit():
            solicitante, assunto = g("solicitante"), g("assunto")
            prioridade = g("prioridade") if g("prioridade") in PRIORIDADES else "normal"
            if solicitante and assunto:      # campos obrigatórios: não deixa esvaziar
                conn.execute(
                    "UPDATE solicitacoes SET solicitante = ?, assunto = ?, "
                    "descricao = ?, prioridade = ?, categoria = ? WHERE id = ?",
                    (solicitante, assunto, g("descricao"), prioridade,
                     canonizar(conn, "categoria", g("categoria")), int(g("id"))),
                )

        elif action == "atribuir" and g("id").isdigit():
            # o form de suporte não manda previsão; sem esse if o campo seria zerado
            sets, args = ["dev = ?"], [canonizar(conn, "dev", g("dev"))]
            if "previsao" in form:
                sets.append("previsao = ?")
                args.append(ler_data(g("previsao")) or None)
            conn.execute(
                f"UPDATE solicitacoes SET {', '.join(sets)} WHERE id = ?",
                args + [int(g("id"))],
            )

        elif action == "anotar" and g("id").isdigit() and g("texto"):
            conn.execute(
                "INSERT INTO anotacoes (solicitacao_id, texto, publica) VALUES (?, ?, ?)",
                (int(g("id")), g("texto"), 1 if g("publica") else 0),
            )

        elif action == "nota_visivel" and g("nota").isdigit():
            conn.execute(
                "UPDATE anotacoes SET publica = 1 - publica WHERE id = ?", (int(g("nota")),)
            )

        elif action == "apagar_nota" and g("nota").isdigit():
            conn.execute("DELETE FROM anotacoes WHERE id = ?", (int(g("nota")),))

        elif action == "atender" and g("id").isdigit():
            conn.execute(
                "UPDATE solicitacoes SET status = ?, concluido_em = NULL WHERE id = ?",
                (STATUS_ATENDIMENTO, int(g("id"))),
            )

        elif action == "concluir" and g("id").isdigit():
            conn.execute(
                "UPDATE solicitacoes SET status = ?, concluido_em = datetime('now') WHERE id = ?",
                (STATUS_CONCLUIDO, int(g("id"))),
            )

        elif action == "reabrir" and g("id").isdigit():
            conn.execute(
                "UPDATE solicitacoes SET status = ?, concluido_em = NULL WHERE id = ?",
                (STATUS_FILA, int(g("id"))),
            )

        elif action == "excluir" and g("id").isdigit():
            conn.execute(
                "DELETE FROM anotacoes WHERE solicitacao_id = ?", (int(g("id")),)
            )
            conn.execute("DELETE FROM solicitacoes WHERE id = ?", (int(g("id")),))

        conn.commit()
    finally:
        conn.close()


def salvar_avaliacao(form: dict) -> str:
    """Grava a nota do solicitante. Devolve o token, pro redirect voltar na página."""
    def g(k: str) -> str:
        return (form.get(k, [""])[0] or "").strip()

    token, nota = g("t"), g("nota")
    if not token or not nota.isdigit() or int(nota) not in dict(NOTAS):
        return token
    conn = get_db()
    try:
        conn.execute(
            "UPDATE solicitacoes SET nota = ?, nota_obs = ?, "
            "nota_em = datetime('now') WHERE token = ? AND status = ?",
            (int(nota), g("obs")[:1000], token, STATUS_CONCLUIDO),
        )
        conn.commit()
    finally:
        conn.close()
    return token


def abrir_solicitacao(form: dict) -> tuple:
    """Abertura feita pelo próprio solicitante. Devolve (token, erro).

    Prioridade e responsável não vêm daqui de propósito: quem abre não define
    a própria urgência nem escolhe quem atende — isso continua sendo da equipe.
    """
    def g(k: str) -> str:
        return (form.get(k, [""])[0] or "").strip()

    fila = g("fila")
    nome, assunto, descricao = g("solicitante")[:120], g("assunto")[:160], g("descricao")[:2000]
    if fila not in FILAS:
        return "", "Escolha se é um atendimento de suporte ou uma demanda nova."
    if not nome or not assunto:
        return "", "Preencha seu nome e o assunto."

    token = novo_token()
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO solicitacoes "
            "(solicitante, assunto, descricao, prioridade, fila, token) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (nome, assunto, descricao, "normal", fila, token),
        )
        conn.commit()
    finally:
        conn.close()
    return token, ""


# -----------------------------------------------------------------------------
# Renderização
# -----------------------------------------------------------------------------
CSS = """
    :root {
        --paper:  #eceff3;
        --surface:#ffffff;
        --ink:    #16202b;
        --muted:  #64717f;
        --line:   #d9e0e8;
        --signal: #2f5ee0;
        --signal-ink:#1f47b8;
        --wait-bg:#fbf0dc; --wait-ink:#8a5600;
        --live-bg:#dff3ee; --live-ink:#0a6f5d;
        --alta-bg:#fbe3e3; --alta-ink:#a4302c;
        --late-bg:#fbe3e3; --late-ink:#a4302c;
        --due-bg: #fbf0dc; --due-ink: #8a5600;
        --dev-bg: #e9e9fb; --dev-ink: #4a3fa8;
    }
    * { box-sizing: border-box; }
    body {
        margin: 0; background: var(--paper); color: var(--ink);
        font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    .mono { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }
    .wrap { max-width: 940px; margin: 0 auto; padding: 32px 20px 80px; }
    header.top { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 4px; }
    header.top h1 { font-size: 22px; letter-spacing: -0.01em; margin: 0; font-weight: 650; }
    header.top .counts { color: var(--muted); font-size: 13px; margin-left: auto; }
    header.top .counts b { color: var(--ink); font-weight: 600; }
    .sub { color: var(--muted); font-size: 13.5px; margin: 2px 0 26px; }
    .layout { display: grid; grid-template-columns: 320px 1fr; gap: 24px; align-items: start; }
    @media (max-width: 760px) { .layout { grid-template-columns: 1fr; } }
    .card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 20px; }
    form.new { position: sticky; top: 24px; }
    form.new h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 16px; font-weight: 600; }
    label { display: block; font-size: 12.5px; color: var(--muted); margin: 14px 0 5px; font-weight: 500; }
    label:first-of-type { margin-top: 0; }
    input, textarea, select {
        width: 100%; font: inherit; color: var(--ink);
        background: #fbfcfd; border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px;
    }
    input:focus, textarea:focus, select:focus {
        outline: none; border-color: var(--signal);
        box-shadow: 0 0 0 3px rgba(47,94,224,.14); background: #fff;
    }
    textarea { resize: vertical; min-height: 62px; }
    .btn {
        display: inline-flex; align-items: center; gap: 7px; font: inherit; font-weight: 550;
        cursor: pointer; border: 1px solid transparent; border-radius: 8px; padding: 9px 14px;
    }
    .btn.primary { width: 100%; justify-content: center; margin-top: 18px; background: var(--signal); color: #fff; }
    .btn.primary:hover { background: var(--signal-ink); }
    .btn.ghost { background: #fff; border-color: var(--line); color: var(--ink); padding: 6px 11px; font-size: 13px; }
    .btn.ghost:hover { border-color: #b9c3ce; }
    .btn.ghost.danger:hover { border-color: var(--alta-ink); color: var(--alta-ink); }
    section h2.section { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 12px; font-weight: 600; }
    form.filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 0 0 12px; }
    form.filters input[type="search"] { flex: 1 1 190px; width: auto; }
    form.filters select { width: auto; flex: 0 0 auto; }
    form.filters .btn { flex: 0 0 auto; }
    .found { color: var(--muted); font-size: 12.5px; margin: -4px 0 12px; }
    .found b { color: var(--ink); font-weight: 600; }
    .found a { color: var(--signal); text-decoration: none; margin-left: 8px; }
    .found a:hover { text-decoration: underline; }
    .queue { display: flex; flex-direction: column; gap: 10px; }
    .ticket { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; display: grid; grid-template-columns: 52px 1fr; overflow: hidden; }
    .ticket .pos { display: flex; flex-direction: column; align-items: center; justify-content: center; border-right: 1px solid var(--line); background: #f6f8fb; padding: 12px 0; }
    .ticket .pos .n { font-size: 18px; font-weight: 600; color: var(--muted); }
    .ticket .body { padding: 14px 16px; }
    .ticket.next { border-color: var(--signal); box-shadow: 0 0 0 1px var(--signal); }
    .ticket.next .pos { background: var(--signal); }
    .ticket.next .pos .n { color: #fff; }
    .eyebrow { font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--signal); font-weight: 700; margin-bottom: 4px; }
    .ticket .title { font-weight: 600; font-size: 15.5px; }
    .ticket .meta { color: var(--muted); font-size: 12.5px; margin-top: 3px; }
    .ticket .desc { margin: 9px 0 0; color: #384454; font-size: 13.5px; white-space: pre-wrap; }
    .tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 11px; }
    .tag { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 999px; letter-spacing: .02em; }
    .tag.wait { background: var(--wait-bg); color: var(--wait-ink); }
    .tag.live { background: var(--live-bg); color: var(--live-ink); }
    .tag.alta { background: var(--alta-bg); color: var(--alta-ink); }
    .tag.plain { background: #eef1f5; color: var(--muted); }
    .tag.late { background: var(--late-bg); color: var(--late-ink); }
    .tag.due  { background: var(--due-bg);  color: var(--due-ink); }
    .tag.dev  { background: var(--dev-bg);  color: var(--dev-ink); }
    nav.filas { display: flex; gap: 4px; margin: 0 0 22px; border-bottom: 1px solid var(--line); }
    nav.filas a {
        text-decoration: none; color: var(--muted); font-size: 14px; font-weight: 550;
        padding: 9px 14px; border-bottom: 2px solid transparent; margin-bottom: -1px;
    }
    nav.filas a:hover { color: var(--ink); }
    nav.filas a.on { color: var(--signal); border-bottom-color: var(--signal); }
    nav.filas a .pill {
        background: #eef1f5; color: var(--muted); font-size: 11px; font-weight: 600;
        border-radius: 999px; padding: 1px 7px; margin-left: 6px;
    }
    nav.filas a.on .pill { background: var(--signal); color: #fff; }
    nav.filas a .pill.bad { background: var(--alta-ink); color: #fff; }
    a.alerta, div.alerta {
        display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        background: var(--alta-bg); color: var(--alta-ink); border: 1px solid #f0c9c7;
        border-radius: 10px; padding: 11px 15px; margin: 0 0 22px;
        font-size: 13.5px; text-decoration: none;
    }
    a.alerta:hover { border-color: var(--alta-ink); }
    .alerta b { font-weight: 700; }
    .alerta .ver { margin-left: auto; font-weight: 600; }
    .ticket.alert { border-color: #f0c9c7; box-shadow: 0 0 0 1px #f0c9c7; }
    .ticket.alert .pos { background: var(--alta-bg); }
    .ticket.alert .pos .n { color: var(--alta-ink); }
    .tag.cat { background: #e4f0e6; color: #2f6b3d; }
    /* fechados ficam lado a lado como botões; o que abrir ocupa a linha toda */
    .tools { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 11px; }
    details.tool { flex: 0 0 auto; }
    details.tool[open] { flex: 1 1 100%; }
    details.tool > summary {
        cursor: pointer; list-style: none; display: inline-block;
        background: #fff; border: 1px solid var(--line); border-radius: 8px;
        padding: 6px 11px; font-size: 13px; font-weight: 550; color: var(--ink);
    }
    details.tool > summary::-webkit-details-marker { display: none; }
    details.tool > summary:hover { border-color: #b9c3ce; }
    details.tool[open] > summary { border-color: var(--signal); color: var(--signal); }
    details.tool .painel {
        margin-top: 11px; padding: 13px; background: #f8fafc;
        border: 1px solid var(--line); border-radius: 10px;
    }
    details.tool .painel label:first-of-type { margin-top: 0; }
    details.tool .painel .btn.primary { margin-top: 13px; width: auto; padding: 8px 16px; }
    .linha2 { display: flex; gap: 10px; flex-wrap: wrap; }
    .linha2 > div { flex: 1 1 140px; }
    .nota { border-left: 2px solid var(--line); padding: 0 0 0 11px; margin-bottom: 11px; }
    .nota .cab { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; }
    .nota .cab .tag { font-size: 10.5px; padding: 1px 8px; }
    .nota .cab .qdo { color: var(--muted); font-size: 11.5px; }
    .nota .txt { font-size: 13.5px; white-space: pre-wrap; margin-top: 2px; }
    .nota .btn { padding: 1px 7px; font-size: 11px; }
    .nova-nota { display: flex; gap: 8px; align-items: flex-start; margin-top: 12px; flex-wrap: wrap; }
    .nova-nota textarea { min-height: 40px; font-size: 13.5px; flex: 1 1 100%; }
    .nova-nota label.check { flex: 1 1 auto; margin: 0; }
    /* ---- painel ---- */
    .etapa { margin-bottom: 44px; }
    .etapa-cab { margin-bottom: 18px; }
    .etapa-cab .passo {
        display: inline-block; font-size: 10.5px; font-weight: 700; letter-spacing: .08em;
        text-transform: uppercase; color: var(--signal); background: #e8eeff;
        border-radius: 999px; padding: 3px 10px; margin-bottom: 9px;
    }
    .etapa-cab h2 { font-size: 19px; margin: 0; font-weight: 650; letter-spacing: -0.01em; }
    .etapa-cab p { color: var(--muted); font-size: 13.5px; margin: 4px 0 0; }
    form.periodos { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 18px; }
    .chip {
        font: inherit; font-size: 13px; font-weight: 550; cursor: pointer;
        background: #fff; border: 1px solid var(--line); border-radius: 999px;
        padding: 6px 14px; color: var(--muted);
    }
    .chip:hover { border-color: #b9c3ce; color: var(--ink); }
    .chip.on { background: var(--signal); border-color: var(--signal); color: #fff; }
    .hero-card {
        background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
        padding: 22px 24px; margin-bottom: 14px;
    }
    .hero-num { font-size: 52px; line-height: 1; font-weight: 650; letter-spacing: -0.03em; }
    .hero-lbl { color: var(--muted); font-size: 13.5px; margin-top: 6px; }
    .kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: 12px; margin-bottom: 14px; }
    .tile { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 15px 17px; }
    .tile .rot { color: var(--muted); font-size: 12px; font-weight: 550; }
    .tile .val { font-size: 26px; font-weight: 650; letter-spacing: -0.02em; margin-top: 4px; }
    .tile .nota { color: var(--muted); font-size: 11.5px; margin-top: 4px; line-height: 1.35; }
    .viz-card { background: var(--surface); border: 1px solid var(--line); border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; }
    .viz-card h3 { font-size: 14.5px; margin: 0; font-weight: 620; }
    .viz-sub { color: var(--muted); font-size: 12.5px; margin: 3px 0 14px; }
    .viz { width: 100%; height: auto; display: block; overflow: visible; }
    .viz-vazio { color: var(--muted); font-size: 13px; text-align: center; padding: 26px 10px; background: #fafbfc; border: 1px dashed var(--line); border-radius: 10px; margin: 0; }
    .viz-dupla { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    @media (max-width: 760px) { .viz-dupla { grid-template-columns: 1fr; } }
    .viz-leg { display: flex; gap: 15px; flex-wrap: wrap; margin-bottom: 10px; }
    .viz-leg span { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); }
    .viz-leg i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
    details.viz-tab { margin-top: 12px; }
    details.viz-tab > summary { font-size: 12px; padding: 4px 10px; font-weight: 500; color: var(--muted); }
    table.tab { width: 100%; border-collapse: collapse; font-size: 12.5px; }
    table.tab th { text-align: left; color: var(--muted); font-weight: 600; padding: 5px 8px; border-bottom: 1px solid var(--line); }
    table.tab td { padding: 5px 8px; border-bottom: 1px solid var(--line); font-variant-numeric: tabular-nums; }
    table.tab tr:last-child td { border-bottom: none; }
    .grupo { margin-bottom: 34px; }
    .grupo p.hint { color: var(--muted); font-size: 13px; margin: -4px 0 12px; }
    .grupo .badge { color: var(--alta-ink); font-weight: 700; }
    .assign { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 12px;
              padding-top: 12px; border-top: 1px dashed var(--line); }
    .assign input { width: auto; flex: 1 1 130px; padding: 6px 9px; font-size: 13px; }
    .assign input[type="date"] { flex: 0 0 auto; }
    .assign .btn { padding: 6px 11px; font-size: 13px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 13px; }
    form.inline { display: inline; margin: 0; }
    .empty { border: 1px dashed var(--line); border-radius: 12px; padding: 30px 20px; text-align: center; color: var(--muted); background: #fafbfc; }
    details.done { margin-top: 30px; }
    details.done > summary { cursor: pointer; font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); font-weight: 600; list-style: none; }
    details.done > summary::-webkit-details-marker { display: none; }
    details.done > summary::before { content: "\\25B8 "; }
    details.done[open] > summary::before { content: "\\25BE "; }
    .done-item { border-bottom: 1px solid var(--line); padding-bottom: 4px; }
    .done-row { display: flex; align-items: center; gap: 12px; padding: 10px 4px; font-size: 13.5px; }
    .done-row .did { color: var(--muted); font-size: 12px; min-width: 88px; }
    .done-row .who { color: var(--muted); }
    .done-row .txt { flex: 1; }
    .done-row s { color: var(--muted); text-decoration-color: var(--line); }
    .tag.nota { background: #fdf0d5; color: #8a5600; }

    /* compartilhar: link de avaliação de um item concluído */
    details.share > summary { cursor: pointer; font-size: 12px; color: var(--signal-ink); list-style: none; white-space: nowrap; }
    details.share > summary::-webkit-details-marker { display: none; }
    .share-box { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; padding: 8px 4px 4px; }
    .share-box input { flex: 1 1 260px; width: auto; padding: 6px 9px; font-size: 12.5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: #f7f9fb; }
    .share-box .btn { padding: 6px 11px; font-size: 12.5px; }
    .share-box .obs { flex: 1 1 100%; color: var(--muted); font-size: 12.5px; margin: 0; }

    /* página pública de avaliação */
    .pub { max-width: 620px; }
    .pub .sub { margin-bottom: 22px; }
    .dados { display: grid; grid-template-columns: auto 1fr; gap: 8px 16px; margin: 0 0 4px; font-size: 14px; }
    .dados dt { color: var(--muted); }
    .dados dd { margin: 0; }
    .rate { display: flex; gap: 8px; flex-wrap: wrap; margin: 6px 0 18px; }
    .pub h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--muted); margin: 0 0 4px; font-weight: 600; }
    .rate label { flex: 1 1 92px; position: relative; cursor: pointer; margin: 0; }
    .rate input { position: absolute; opacity: 0; width: 0; height: 0; }
    .rate span { display: block; text-align: center; border: 1px solid var(--line); border-radius: 10px; padding: 10px 6px; background: var(--surface); }
    .rate b { display: block; font-size: 19px; line-height: 1.3; }
    .rate small { color: var(--muted); font-size: 11.5px; }
    .rate input:checked + span { border-color: var(--signal); box-shadow: 0 0 0 2px rgba(47,94,224,.18); background: #f3f6ff; }
    .rate input:focus-visible + span { outline: 2px solid var(--signal); outline-offset: 2px; }
    .rate input:checked + span small { color: var(--signal-ink); }
    .obrigado { border: 1px solid var(--live-ink); background: var(--live-bg); color: var(--live-ink); border-radius: 12px; padding: 12px 16px; font-size: 14px; margin-bottom: 18px; }
    .erro { border: 1px solid var(--alta-ink); background: var(--alta-bg); color: var(--alta-ink); border-radius: 12px; padding: 12px 16px; font-size: 14px; margin-bottom: 18px; }
    .rate.tipos label { flex: 1 1 210px; display: flex; }
    .rate.tipos span { text-align: left; padding: 12px 14px; flex: 1; }
    .rate.tipos b { font-size: 15px; }
    .pub .hero-card { margin: 0; }
    .pub .card p { font-size: 14px; margin: 0 0 6px; }
    .pub .card p:last-child { margin-bottom: 0; }
    .pub .card .viz-sub { margin-top: 8px; }
    /* caixa com o link público, no rodapé do formulário interno */
    .convite { margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--line); }
    .convite p { font-size: 12.5px; color: var(--muted); margin: 0 0 8px; }
    .convite .share-box { padding: 0; }
    .tag.vis { background: var(--live-bg); color: var(--live-ink); }
    label.check { display: flex; align-items: center; gap: 7px; margin: 8px 0 0; font-size: 12.5px; cursor: pointer; }
    label.check input { width: auto; margin: 0; }
    ul.andamento { list-style: none; margin: 0; padding: 0; }
    ul.andamento li { border-left: 2px solid var(--line); padding: 0 0 14px 14px; position: relative; }
    ul.andamento li:last-child { padding-bottom: 0; }
    ul.andamento li::before { content: ""; position: absolute; left: -5px; top: 5px; width: 8px; height: 8px; border-radius: 50%; background: var(--signal); }
    ul.andamento .qdo { color: var(--muted); font-size: 12px; }
    ul.andamento p { margin: 2px 0 0; font-size: 14px; }
"""


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
<title>Fila de Suporte · {titulo}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
    <header class="top">
        <h1>Fila de Suporte</h1>
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
<title>{titulo}</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap pub">
    <header class="top"><h1>{h1}</h1></header>
    {corpo}
</div>
<script>{SCRIPT}</script>
</body>
</html>"""


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


def serie_temporal(concluidos, dias_periodo: int):
    """(rótulos, série suporte, série demandas). Vira semanal em período longo."""
    hoje = datetime.now(LOCAL_TZ).date()
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


def coletar_metricas(conn: sqlite3.Connection, dias_periodo: int) -> dict:
    agora = datetime.now(timezone.utc)
    hoje = datetime.now(LOCAL_TZ).date()

    extra, args = "", []
    if dias_periodo:
        extra = " AND concluido_em >= ?"
        args = [(agora - timedelta(days=dias_periodo)).strftime("%Y-%m-%d %H:%M:%S")]
    concluidos = conn.execute(
        "SELECT * FROM solicitacoes WHERE status = ? AND concluido_em IS NOT NULL" + extra,
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
    if dias_periodo:
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
        "serie": serie_temporal(concluidos, dias_periodo),
    }


def render_painel(dias_periodo: int) -> str:
    conn = get_db()
    try:
        m = coletar_metricas(conn, dias_periodo)
        al = buscar_alertas(conn)
        por_fila = dict(
            conn.execute(
                "SELECT fila, COUNT(*) FROM solicitacoes WHERE status IN (?, ?) GROUP BY fila",
                (STATUS_FILA, STATUS_ATENDIMENTO),
            ).fetchall()
        )
    finally:
        conn.close()

    rot_periodo = dict(PERIODOS)[dias_periodo]
    n_concl = len(m["concluidos"])
    n_abertos = len(m["abertos"])

    def tile(rotulo, valor, nota=""):
        nota = f'<div class="nota">{nota}</div>' if nota else ""
        return f"""<div class="tile"><div class="rot">{rotulo}</div>
            <div class="val">{valor}</div>{nota}</div>"""

    # ---------- etapa 1: feito ----------
    rotulos, sup, dem = m["serie"]
    granularidade = "por dia" if dias_periodo and dias_periodo <= 30 else "por semana"
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

    # avaliações: nota mais alta = azul mais escuro da rampa
    n_aval = len(m["avaliadas"])
    graf_notas = svg_barras_h(m["dist_notas"], cores=list(reversed(RAMPA_IDADE)),
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

        <form class="periodos" method="get" action="{PATH_PAINEL}">
            {"".join(
                f'<button class="chip{" on" if d == dias_periodo else ""}" '
                f'name="dias" value="{d}" type="submit">{r}</button>'
                for d, r in PERIODOS)}
        </form>

        <div class="hero-card">
            <div class="hero-num">{n_concl}</div>
            <div class="hero-lbl">concluídos · {"todo o histórico" if not dias_periodo
                else "últimos " + rot_periodo.lower()}</div>
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
    graf_idade = svg_barras_h(m["idades"], cores=list(RAMPA_IDADE))
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
               Quanto mais escuro, mais tempo parado.</p>
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

    return shell(
        "Painel",
        "Duas etapas: o que já foi feito e o que vem pela frente.",
        f'<div class="counts"><b>{n_concl}</b> concluídos · <b>{n_abertos}</b> abertos</div>',
        render_abas(PATH_PAINEL, por_fila, al["total"]),
        render_banner(al, aqui=False),
        feito + previsao,
    )


def render_page(fila: str, f: dict) -> str:
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


# -----------------------------------------------------------------------------
# Servidor HTTP
# -----------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send_html(self, body: str, status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == PATH_ABRIR:
            q = parse_qs(url.query)
            token = (q.get("ok", [""])[0] or "").strip()
            if token:
                corpo, status = render_confirmacao(token)
                self._send_html(corpo, status)
            else:
                self._send_html(render_abrir((q.get("tipo", [""])[0] or "").strip()))
            return
        if url.path == PATH_AVALIAR:
            q = parse_qs(url.query)
            corpo, status = render_avaliacao(
                (q.get("t", [""])[0] or "").strip(), salvo=q.get("ok") == ["1"]
            )
            self._send_html(corpo, status)
            return
        if url.path == PATH_ALERTAS:
            self._send_html(render_alertas())
            return
        if url.path == PATH_PAINEL:
            bruto = parse_qs(url.query).get("dias", ["30"])[0]
            validos = [d for d, _ in PERIODOS]
            dias = int(bruto) if bruto.isdigit() and int(bruto) in validos else 30
            self._send_html(render_painel(dias))
            return
        rotas = {v["path"]: k for k, v in FILAS.items()}
        if url.path not in rotas:
            self._send_html("<h1>404</h1>", 404)
            return
        filtros = ler_filtros(parse_qs(url.query, keep_blank_values=True))
        self._send_html(render_page(rotas[url.path], filtros))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = parse_qs(raw, keep_blank_values=True)

        caminho = urlparse(self.path).path

        # abertura pública: erro volta pro formulário, sucesso vai pro recibo
        if caminho == PATH_ABRIR:
            token, erro = abrir_solicitacao(form)
            if erro:
                self._send_html(render_abrir(
                    (form.get("fila", [""])[0] or "").strip(), erro,
                    {k: (form.get(k, [""])[0] or "")
                     for k in ("solicitante", "assunto", "descricao")},
                ), 400)
                return
            self.send_response(303)
            self.send_header("Location", f"{PATH_ABRIR}?ok={quote(token)}")
            self.end_headers()
            return

        # avaliação vem da página pública e volta pra ela, não pra fila
        if caminho == PATH_AVALIAR:
            token = salvar_avaliacao(form)
            self.send_response(303)
            self.send_header("Location", f"{PATH_AVALIAR}?t={quote(token)}&ok=1")
            self.end_headers()
            return

        handle_action(form)

        # ação disparada da tela de alertas volta pra lá; senão, pra própria fila
        voltar = (form.get("voltar", [""])[0] or "").strip()
        if voltar == PATH_ALERTAS:
            destino = PATH_ALERTAS
        else:
            fila = (form.get("fila", [""])[0] or "").strip()
            destino = FILAS[fila if fila in FILAS else FILA_SUPORTE]["path"]
            destino += query_string(ler_filtros(form))

        self.send_response(303)                 # PRG: redireciona pra GET
        self.send_header("Location", destino)
        self.end_headers()

    def log_message(self, fmt, *args):          # log enxuto
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))


def ip_local() -> str:
    """IP desta máquina na rede local (só para exibir no terminal)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 1))     # não envia nada; só resolve a rota de saída
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main() -> None:
    init_db()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    base = f"http://localhost:{PORT}"
    print(f"\n  Fila de Suporte rodando em  {base}")
    if HOST == "0.0.0.0":
        base = f"http://{ip_local()}:{PORT}"
        print(f"  Na rede local (mesmo Wi-Fi):  {base}")
    print(f"  Abertura pelo solicitante:    {base}{PATH_ABRIR}")
    print(f"  Banco: {DB_PATH}")
    print("  Ctrl+C para parar.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Encerrado.")
        server.server_close()


if __name__ == "__main__":
    main()
