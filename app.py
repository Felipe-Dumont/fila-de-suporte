#!/usr/bin/env python3
"""
SolicitaMais — app em Python + SQLite.
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

from configuracao.ambiente import carregar_ambiente

carregar_ambiente()

from configuracao.cores import COR_DEMANDAS, COR_EIXO_GRAFICO, COR_GRADE_GRAFICO
from configuracao.cores import COR_SUPORTE, COR_TEXTO_GRAFICO, COR_TEXTO_SUAVE_GRAFICO
from configuracao.cores import RAMPA_ATRASO, RAMPA_AVALIACAO, gerar_variaveis_css
from rotas.api import atender_get as atender_get_api
from rotas.api import atender_post as atender_post_api
from rotas.api import configurar as configurar_api
from rotas.kanban import PATH_KANBAN
from rotas.kanban import atender_get as atender_get_kanban
from rotas.kanban import atender_post as atender_post_kanban
from rotas.kanban import configurar as configurar_kanban

try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
except Exception:                       # sistema sem base de fusos: cai pro offset fixo
    LOCAL_TZ = timezone(timedelta(hours=-3))

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.sqlite")
LOGO_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "imagens", "logo-solicitamais.png"
)
ICONE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "imagens",
    "logo-icone-solicitamais-favicon.png",
)
PATH_LOGO = "/imagens/logo-solicitamais.png"
PATH_ICONE = "/imagens/logo-icone-solicitamais-favicon.png"
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("FILA_PORT", "8000"))
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

# Gráficos seguem a mesma paleta centralizada usada pela interface.
VIZ_GRID = COR_GRADE_GRAFICO
VIZ_EIXO = COR_EIXO_GRAFICO
VIZ_INK = COR_TEXTO_GRAFICO
VIZ_MUTED = COR_TEXTO_SUAVE_GRAFICO

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
        ("origem_sistema", "TEXT NOT NULL DEFAULT ''"),
        ("origem_usuario_id", "INTEGER"),
        ("origem_usuario_nome", "TEXT NOT NULL DEFAULT ''"),
        ("origem_usuario_email", "TEXT NOT NULL DEFAULT ''"),
    )
    for nome, ddl in novas:
        if nome not in existentes:
            conn.execute(f"ALTER TABLE solicitacoes ADD COLUMN {nome} {ddl}")

    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sol_token ON solicitacoes (token)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sol_origem_usuario "
        "ON solicitacoes (origem_sistema, origem_usuario_id)"
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
        classe = "critical" if atraso >= 3 else "late"
        return f"Atrasada {atraso}d · era {quando_txt}", classe
    if dias == 0:
        return f"Entrega hoje · {quando_txt}", "due"
    if dias == 1:
        return f"Entrega amanhã · {quando_txt}", "due"
    return f"Entrega {quando_txt} · em {dias}d", "scheduled"


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


def nivel_atraso(s: sqlite3.Row, fila: str) -> str:
    """Classifica alertas em atenção ou crítico sem alterar a ordem da fila."""
    if not em_alerta(s, fila):
        return ""

    if fila == FILA_DEMANDAS:
        try:
            previsao = date.fromisoformat(s["previsao"])
        except ValueError:
            return ""
        dias_atraso = (datetime.now(LOCAL_TZ).date() - previsao).days

        return "critico" if dias_atraso >= 3 else "atencao"

    idade = datetime.now(timezone.utc) - _parse_utc(s["criado_em"])

    return "critico" if idade >= timedelta(days=3) else "atencao"


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
__VARIAVEIS_DE_COR__
    }
    * { box-sizing: border-box; }
    body {
        margin: 0; background: var(--paper); color: var(--ink);
        font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    }
    .mono { font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace; }
    .wrap { max-width: 940px; margin: 0 auto; padding: 32px 20px 80px; }
    header.top { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 4px; }
    header.top h1 { font-size: 22px; letter-spacing: -0.01em; margin: 0; font-weight: 650; }
    .brand-logo { width: 185px; height: 64px; object-fit: cover; object-position: center; border-radius: 8px; }
    .pub header.top { align-items: center; }
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
        background: var(--field-bg); border: 1px solid var(--line); border-radius: 8px; padding: 9px 11px;
    }
    input:focus, textarea:focus, select:focus {
        outline: none; border-color: var(--signal);
        box-shadow: 0 0 0 3px rgba(var(--signal-rgb),.16); background: var(--surface);
    }
    textarea { resize: vertical; min-height: 62px; }
    .btn {
        display: inline-flex; align-items: center; gap: 7px; font: inherit; font-weight: 550;
        cursor: pointer; border: 1px solid transparent; border-radius: 8px; padding: 9px 14px;
    }
    .btn.primary { width: 100%; justify-content: center; margin-top: 18px; background: var(--signal); color: var(--surface); }
    .btn.primary:hover { background: var(--signal-ink); }
    .btn.ghost { background: var(--surface); border-color: var(--line); color: var(--ink); padding: 6px 11px; font-size: 13px; }
    .btn.ghost:hover { border-color: var(--line-strong); }
    .btn.ghost.danger:hover { border-color: var(--danger); color: var(--danger); }
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
    .ticket .pos { display: flex; flex-direction: column; align-items: center; justify-content: center; border-right: 1px solid var(--line); background: var(--surface-soft); padding: 12px 0; }
    .ticket .pos .n { font-size: 18px; font-weight: 600; color: var(--muted); }
    .ticket .body { padding: 14px 16px; }
    .ticket.next { border-color: var(--signal); box-shadow: 0 0 0 1px var(--signal); }
    .ticket.next .pos { background: var(--signal); }
    .ticket.next .pos .n { color: var(--surface); }
    .eyebrow { font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--signal); font-weight: 700; margin-bottom: 4px; }
    .ticket .title { font-weight: 600; font-size: 15.5px; }
    .ticket .meta { color: var(--muted); font-size: 12.5px; margin-top: 3px; }
    .ticket .desc { margin: 9px 0 0; color: var(--text-secondary); font-size: 13.5px; white-space: pre-wrap; }
    .tags { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 11px; }
    .tag { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 999px; letter-spacing: .02em; }
    .tag.wait { background: var(--wait-bg); color: var(--wait-ink); }
    .tag.live { background: var(--live-bg); color: var(--live-ink); }
    .tag.alta { background: var(--alta-bg); color: var(--alta-ink); }
    .tag.plain { background: var(--surface-muted); color: var(--muted); }
    .tag.late { background: var(--late-bg); color: var(--late-ink); }
    .tag.due  { background: var(--due-bg);  color: var(--due-ink); }
    .tag.scheduled { background: var(--scheduled-bg); color: var(--scheduled-ink); }
    .tag.critical { background: var(--critical-bg); color: var(--critical-ink); }
    .tag.dev  { background: var(--dev-bg);  color: var(--dev-ink); }
    nav.filas { display: flex; gap: 4px; margin: 0 0 22px; border-bottom: 1px solid var(--line); }
    nav.filas a {
        text-decoration: none; color: var(--muted); font-size: 14px; font-weight: 550;
        padding: 9px 14px; border-bottom: 2px solid transparent; margin-bottom: -1px;
    }
    nav.filas a:hover { color: var(--ink); }
    nav.filas a.on { color: var(--signal); border-bottom-color: var(--signal); }
    nav.filas a .pill {
        background: var(--surface-muted); color: var(--muted); font-size: 11px; font-weight: 600;
        border-radius: 999px; padding: 1px 7px; margin-left: 6px;
    }
    nav.filas a.on .pill { background: var(--signal); color: var(--surface); }
    nav.filas a .pill.bad { background: var(--danger); color: var(--danger-ink); }
    a.alerta, div.alerta {
        display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
        background: var(--alta-bg); color: var(--alta-ink); border: 1px solid var(--danger-line);
        border-radius: 10px; padding: 11px 15px; margin: 0 0 22px;
        font-size: 13.5px; text-decoration: none;
    }
    a.alerta:hover { border-color: var(--danger); }
    .alerta b { font-weight: 700; }
    .alerta .ver { margin-left: auto; font-weight: 600; }
    .ticket.atencao { border-color: var(--warning); box-shadow: 0 0 0 1px var(--warning); }
    .ticket.atencao .pos { background: var(--warning); }
    .ticket.atencao .pos .n { color: var(--warning-ink); }
    .ticket.critico { border-color: var(--danger); box-shadow: 0 0 0 1px var(--danger); }
    .ticket.critico .pos { background: var(--danger); }
    .ticket.critico .pos .n { color: var(--danger-ink); }
    .tag.cat { background: var(--accent-bg); color: var(--accent-ink); }
    /* fechados ficam lado a lado como botões; o que abrir ocupa a linha toda */
    .tools { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 11px; }
    details.tool { flex: 0 0 auto; }
    details.tool[open] { flex: 1 1 100%; }
    details.tool > summary {
        cursor: pointer; list-style: none; display: inline-block;
        background: var(--surface); border: 1px solid var(--line); border-radius: 8px;
        padding: 6px 11px; font-size: 13px; font-weight: 550; color: var(--ink);
    }
    details.tool > summary::-webkit-details-marker { display: none; }
    details.tool > summary:hover { border-color: var(--line-strong); }
    details.tool[open] > summary { border-color: var(--signal); color: var(--signal); }
    details.tool .painel {
        margin-top: 11px; padding: 13px; background: var(--surface-soft);
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
        text-transform: uppercase; color: var(--signal); background: var(--surface-soft);
        border-radius: 999px; padding: 3px 10px; margin-bottom: 9px;
    }
    .etapa-cab h2 { font-size: 19px; margin: 0; font-weight: 650; letter-spacing: -0.01em; }
    .etapa-cab p { color: var(--muted); font-size: 13.5px; margin: 4px 0 0; }
    form.periodos { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 18px; }
    .chip {
        font: inherit; font-size: 13px; font-weight: 550; cursor: pointer;
        background: var(--surface); border: 1px solid var(--line); border-radius: 999px;
        padding: 6px 14px; color: var(--muted);
    }
    .chip:hover { border-color: var(--line-strong); color: var(--ink); }
    .chip.on { background: var(--signal); border-color: var(--signal); color: var(--surface); }
    .hero-card {
        background: var(--surface); border: 1px solid var(--line); border-radius: 12px;
        border-top: 3px solid var(--accent);
        padding: 22px 24px; margin-bottom: 14px;
    }
    .hero-num { color: var(--signal-active); font-size: 52px; line-height: 1; font-weight: 650; letter-spacing: -0.03em; }
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
    .viz-vazio { color: var(--muted); font-size: 13px; text-align: center; padding: 26px 10px; background: var(--surface-soft); border: 1px dashed var(--line); border-radius: 10px; margin: 0; }
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
    .grupo .badge { color: var(--danger); font-weight: 700; }
    .assign { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-top: 12px;
              padding-top: 12px; border-top: 1px dashed var(--line); }
    .assign input { width: auto; flex: 1 1 130px; padding: 6px 9px; font-size: 13px; }
    .assign input[type="date"] { flex: 0 0 auto; }
    .assign .btn { padding: 6px 11px; font-size: 13px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 13px; }
    form.inline { display: inline; margin: 0; }
    .empty { border: 1px dashed var(--line); border-radius: 12px; padding: 30px 20px; text-align: center; color: var(--muted); background: var(--surface-soft); }
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
    .tag.nota { background: var(--rating-bg); color: var(--rating-ink); }

    /* compartilhar: link de avaliação de um item concluído */
    details.share > summary { cursor: pointer; font-size: 12px; color: var(--signal-ink); list-style: none; white-space: nowrap; }
    details.share > summary::-webkit-details-marker { display: none; }
    .share-box { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; padding: 8px 4px 4px; }
    .share-box input { flex: 1 1 260px; width: auto; padding: 6px 9px; font-size: 12.5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; background: var(--surface-soft); }
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
    .rate input:checked + span { border-color: var(--signal); box-shadow: 0 0 0 2px rgba(var(--signal-rgb),.18); background: var(--surface-soft); }
    .rate input:focus-visible + span { outline: 2px solid var(--signal); outline-offset: 2px; }
    .rate input:checked + span small { color: var(--signal-ink); }
    .obrigado { border: 1px solid var(--success); background: var(--live-bg); color: var(--live-ink); border-radius: 12px; padding: 12px 16px; font-size: 14px; margin-bottom: 18px; }
    .erro { border: 1px solid var(--danger); background: var(--alta-bg); color: var(--alta-ink); border-radius: 12px; padding: 12px 16px; font-size: 14px; margin-bottom: 18px; }
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
""".replace("__VARIAVEIS_DE_COR__", gerar_variaveis_css("        "))


from views.abrir.pagina import configurar as configurar_abrir
from views.abrir.pagina import render_abrir, render_confirmacao
from views.alertas.pagina import configurar as configurar_alertas
from views.alertas.pagina import render_alertas
from views.avaliar.pagina import configurar as configurar_avaliar
from views.avaliar.pagina import render_avaliacao
from views.comum.componentes import configurar as configurar_componentes
from views.comum.componentes import render_abas
from views.comum.componentes import render_concluidos, render_edicao, render_notas
from views.comum.componentes import render_share, render_ticket, shell, shell_publico
from views.demandas.pagina import renderizar as render_demandas
from views.filas.pagina import configurar as configurar_filas
from views.painel.pagina import configurar as configurar_painel
from views.painel.pagina import render_painel
from views.suporte.pagina import renderizar as render_suporte

_contexto_views = globals().copy()
configurar_componentes(_contexto_views)
_contexto_views.update({
    "render_abas": render_abas,
    "render_concluidos": render_concluidos,
    "render_edicao": render_edicao,
    "render_notas": render_notas,
    "render_share": render_share,
    "render_ticket": render_ticket,
    "shell": shell,
    "shell_publico": shell_publico,
})
configurar_alertas(_contexto_views)
configurar_abrir(_contexto_views)
configurar_avaliar(_contexto_views)
configurar_painel(_contexto_views)
configurar_filas(_contexto_views)
configurar_api({
    "filas": FILAS,
    "get_db": get_db,
    "novo_token": novo_token,
    "quando": quando,
})
configurar_kanban({
    "buscar_alertas": buscar_alertas,
    "canonizar": canonizar,
    "filas": FILAS,
    "get_db": get_db,
    "normalizar": normalizar,
    "quando": quando,
    "render_abas": render_abas,
    "shell": shell,
    "status_atendimento": STATUS_ATENDIMENTO,
    "status_concluido": STATUS_CONCLUIDO,
    "status_fila": STATUS_FILA,
})



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

    def _send_png(self, caminho: str) -> None:
        try:
            with open(caminho, "rb") as arquivo:
                data = arquivo.read()
        except FileNotFoundError:
            self._send_html("<h1>404</h1>", 404)
            return

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlparse(self.path)
        if atender_get_api(self, url):
            return
        if atender_get_kanban(self, url):
            return
        imagens = {PATH_LOGO: LOGO_PATH, PATH_ICONE: ICONE_PATH}
        if url.path in imagens:
            self._send_png(imagens[url.path])
            return
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
        rotas = {
            FILAS[FILA_SUPORTE]["path"]: render_suporte,
            FILAS[FILA_DEMANDAS]["path"]: render_demandas,
        }
        if url.path not in rotas:
            self._send_html("<h1>404</h1>", 404)
            return
        filtros = ler_filtros(parse_qs(url.query, keep_blank_values=True))
        self._send_html(rotas[url.path](filtros))

    def do_POST(self):
        url = urlparse(self.path)
        if atender_post_api(self, url):
            return
        if atender_post_kanban(self, url):
            return

        caminho = url.path

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        form = parse_qs(raw, keep_blank_values=True)

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
    print(f"\n  SolicitaMais rodando em      {base}")
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
