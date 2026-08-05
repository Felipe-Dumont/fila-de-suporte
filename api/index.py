"""Adapta o Handler HTTP existente para uma Python Function da Vercel."""

from urllib.parse import parse_qs, urlencode, urlparse

import app


app.init_db()


class handler(app.Handler):
    """Restaura a rota original recebida pelo rewrite antes do despacho."""

    def _restaurar_caminho(self) -> None:
        url = urlparse(self.path)
        parametros = parse_qs(url.query, keep_blank_values=True)
        caminho = (parametros.pop("__caminho", [""])[0] or "").strip()
        if not caminho:
            return

        if not caminho.startswith("/"):
            caminho = f"/{caminho}"
        query = urlencode(parametros, doseq=True)
        self.path = caminho + (f"?{query}" if query else "")

    def do_GET(self) -> None:
        self._restaurar_caminho()
        super().do_GET()

    def do_POST(self) -> None:
        self._restaurar_caminho()
        super().do_POST()
