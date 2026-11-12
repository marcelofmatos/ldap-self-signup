"""O menu do painel fica fora do cartão, como abas, com a seção atual destacada."""
from pathlib import Path

import pytest

from tests.unit.test_admin import _login

RAIZ = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("url,ativa", [("/admin/", "Solicitações"), ("/admin/contas", "Contas"),
                                       ("/admin/convidar", "Convidar"),
                                       ("/admin/convidar-por-email", "Convidar por e-mail")])
def test_abas_fora_do_cartao_com_a_ativa(amb, url, ativa):
    _login(amb)
    html = amb.client.get(url).text
    abas = html.index('<nav class="abas"')
    assert abas < html.index('<div class="card">')  # por fora do cartão
    nav = html[abas:html.index("</nav>", abas)]
    assert f'aria-current="page"><span aria-hidden="true">' in nav and f"</span> {ativa}</a>" in nav
    ativo = nav.split('aria-current="page">', 1)[1].split("</a>", 1)[0]
    assert ativo.endswith(f"</span> {ativa}")
    assert nav.count('aria-current="page"') == 1
    assert "</span> Sair (chefe)</button>" in nav


@pytest.mark.parametrize("base", ["app/templates/base.html", "templates-exemplo/exemplo/paginas/base.html"])
def test_bases_tem_o_bloco_de_abas_antes_do_cartao(base):
    fonte = (RAIZ / base).read_text()
    assert fonte.index("{% block abas %}{% endblock %}") < fonte.index('<div class="card">')
