"""O nome e a confirmação do cliente novo ficam num bloco que o script esconde fora de "Novo cliente…"."""
from pathlib import Path

import pytest

from tests.unit.test_admin import _login, _pendente

TEMPLATES = Path(__file__).resolve().parents[2] / "app" / "templates" / "admin"


def _confere(html):
    bloco = html.split('<div class="cliente-novo">', 1)[1].split("</div>", 1)[0]
    assert 'name="organizacao_nova"' in bloco and 'name="confirmar_nova"' in bloco
    assert "cliente-novo" in html.split("<script>", 1)[1] and "__nova__" in html.split("<script>", 1)[1]


@pytest.mark.parametrize("url", ["/admin/convidar", "/admin/convidar-por-email"])
def test_telas_de_convite(amb, url):
    _login(amb)
    _confere(amb.client.get(url).text)


def test_aprovacao(amb):
    sid = _pendente(amb)
    _login(amb)
    _confere(amb.client.get(f"/admin/solicitacao/{sid}").text)


def test_previa_do_lote_usa_o_bloco_e_o_script():
    fonte = (TEMPLATES / "lote_previa.html").read_text()
    assert '<div class="cliente-novo">' in fonte and '{% include "admin/_cliente_novo.html" %}' in fonte
