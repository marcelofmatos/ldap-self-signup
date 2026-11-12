"""Ações do histórico e abas do painel com emoji (decorativo, aria-hidden) e rótulo em português."""
from app.web.admin import EMOJIS_ACAO, ROTULOS_ACAO
from tests.unit.test_admin import _login


def test_toda_acao_com_rotulo_tem_emoji():
    assert set(ROTULOS_ACAO) == set(EMOJIS_ACAO)


def test_filtro_acao_mostra_emoji_decorativo_e_rotulo(amb):
    filtro = amb.app.jinja_env.filters["acao"]
    assert str(filtro("aprovar")) == '<span aria-hidden="true">✅</span> Aprovou'
    assert str(filtro("codigo_novo")) == "codigo_novo"  # sem rótulo: o código, sem emoji


def test_historico_do_detalhe_usa_rotulos(amb):
    sid = amb.banco.criar_solicitacao(
        dict(nome="Maria Souza", cpf="52998224725", email="m@exemplo.org", telefone="+5511912345678",
             justificativa="x"), uid_sugerido="mariasouza", ip="1.1.1.1", user_agent="UA",
        versao_aviso="v", texto_aviso="t", agora=amb.relogio())
    amb.banco.auditar("chefe", "aprovar", f"sol:{sid}", "", amb.relogio())
    _login(amb)
    html = amb.client.get(f"/admin/solicitacao/{sid}").text
    assert '<span aria-hidden="true">✅</span> Aprovou' in html and ">aprovar<" not in html


def test_abas_com_emoji(amb):
    _login(amb)
    nav = amb.client.get("/admin/").text.split('<nav class="abas"', 1)[1].split("</nav>", 1)[0]
    for emoji, rotulo in [("📥", "Solicitações"), ("👥", "Contas"), ("📨", "Convidar"),
                          ("📧", "Convidar por e-mail"), ("🚪", "Sair")]:
        assert f'<span aria-hidden="true">{emoji}</span> {rotulo}' in nav
