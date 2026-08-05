"""Tela pai da fila de suporte."""

from views.filas.pagina import renderizar as renderizar_fila


def renderizar(filtros: dict) -> str:
    return renderizar_fila("suporte", filtros)

