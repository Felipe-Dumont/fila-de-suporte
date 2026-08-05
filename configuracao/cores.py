"""Paleta visual do SolicitaMais, baseada na identidade do LocarMais."""

COR_PRIMARIA = "#6d28d9"
COR_PRIMARIA_HOVER = "#5b21b6"
COR_PRIMARIA_ATIVA = "#4c1d95"
COR_PRIMARIA_CLARA = "#f5f3ff"
COR_PRIMARIA_SUAVE = "#ede9fe"
COR_PRIMARIA_MEDIA = "#c4b5fd"

COR_DESTAQUE = "#ff3399"
COR_DESTAQUE_HOVER = "#e6007a"
COR_DESTAQUE_CLARA = "#fff0f7"

COR_PERIGO = "#dc3545"
COR_SUCESSO = "#28a745"
COR_AVISO = "#ffc107"
COR_INFORMATIVA = "#2563eb"
COR_INFORMATIVA_CLARA = "#60a5fa"
COR_AVISO_FORTE = "#f59e0b"
COR_TEXTO_SEMANTICO = "#ffffff"
COR_TEXTO_AVISO = "#1f2d3d"

CORES_CSS = {
    "paper": "#f5f2f7",
    "surface": "#ffffff",
    "ink": "#2d2133",
    "muted": "#706575",
    "line": "#e3dae8",
    "line-strong": "#cbbfd1",
    "danger": COR_PERIGO,
    "danger-ink": COR_TEXTO_SEMANTICO,
    "success": COR_SUCESSO,
    "success-ink": COR_TEXTO_SEMANTICO,
    "warning": COR_AVISO,
    "warning-ink": COR_TEXTO_AVISO,
    "info": COR_INFORMATIVA,
    "info-ink": COR_TEXTO_SEMANTICO,
    "danger-line": COR_PERIGO,
    "field-bg": "#fcfaff",
    "surface-soft": COR_PRIMARIA_CLARA,
    "surface-muted": "#f1edf4",
    "text-secondary": "#514657",
    "signal": COR_PRIMARIA,
    "signal-ink": COR_PRIMARIA_HOVER,
    "signal-active": COR_PRIMARIA_ATIVA,
    "signal-rgb": "109, 40, 217",
    "accent": COR_DESTAQUE,
    "accent-ink": COR_DESTAQUE_HOVER,
    "accent-bg": COR_DESTAQUE_CLARA,
    "wait-bg": COR_AVISO,
    "wait-ink": COR_TEXTO_AVISO,
    "live-bg": COR_SUCESSO,
    "live-ink": COR_TEXTO_SEMANTICO,
    "alta-bg": COR_PERIGO,
    "alta-ink": COR_TEXTO_SEMANTICO,
    "late-bg": COR_PERIGO,
    "late-ink": COR_TEXTO_SEMANTICO,
    "due-bg": COR_AVISO,
    "due-ink": COR_TEXTO_AVISO,
    "scheduled-bg": COR_INFORMATIVA,
    "scheduled-ink": COR_TEXTO_SEMANTICO,
    "critical-bg": COR_PERIGO,
    "critical-ink": COR_TEXTO_SEMANTICO,
    "rating-bg": COR_AVISO,
    "rating-ink": COR_TEXTO_AVISO,
    "dev-bg": COR_PRIMARIA_SUAVE,
    "dev-ink": COR_PRIMARIA_ATIVA,
}

COR_SUPORTE = COR_PRIMARIA
COR_DEMANDAS = COR_DESTAQUE
RAMPA_AVALIACAO = (
    "#ddd6fe",
    COR_PRIMARIA_MEDIA,
    "#a78bfa",
    COR_PRIMARIA,
    COR_PRIMARIA_ATIVA,
)
RAMPA_ATRASO = (
    COR_INFORMATIVA_CLARA,
    COR_INFORMATIVA,
    COR_AVISO,
    COR_AVISO_FORTE,
    COR_PERIGO,
)

COR_GRADE_GRAFICO = "#e3dae8"
COR_EIXO_GRAFICO = "#c9bdcf"
COR_TEXTO_GRAFICO = "#514657"
COR_TEXTO_SUAVE_GRAFICO = "#85798b"


def gerar_variaveis_css(recuo: str = "") -> str:
    """Transforma a paleta em custom properties usadas pelo CSS da aplicação."""
    return "\n".join(
        f"{recuo}--{nome}: {valor};" for nome, valor in CORES_CSS.items()
    )
