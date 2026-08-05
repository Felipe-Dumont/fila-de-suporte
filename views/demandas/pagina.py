"""Tela pai da fila de demandas."""

from views.filas.pagina import renderizar as renderizar_fila


def renderizar(filtros: dict) -> str:
    return renderizar_fila("demandas", filtros)

