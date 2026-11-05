import re

import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login

PREENCHE = {"nome": "Joana Pereira Lima", "cpf": "123.456.789-09", "telefone": "+55 (11) 98765-4321",
            "justificativa": "", "consentimento": "sim"}


@pytest.fixture
def conv(amb):
    """Convite por e-mail criado pelo admin (que depois sai): guarda o caminho do link e o id."""
    amb.dir.contas["existente"] = dict(uid="existente", cn="E", mail="e@y", ou="CLIENTE-A", cpf="9", telefone="",
                                       senha=None)
    _login(amb)
    r = amb.client.post("/admin/convidar-por-email", data={"acao": "enviar", "email": ["joana@exemplo.org"],
                                                           "organizacao": "CLIENTE-A"},
        follow_redirects=True)
    assert r.status_code == 200
    amb.client.post("/admin/sair")
    amb.link = amb.correio.caminho_do_link()
    [sol] = amb.banco.buscar("joana@exemplo.org", "convidado", 1)
    amb.sid = sol["id"]
    amb.enviados_antes = len(amb.correio.enviados)
    return amb


def _preencher(amb, **over):
    return amb.client.post(amb.link, data={**PREENCHE, **over})


def test_form_em_branco_com_email_fixo(conv):
    r = conv.client.get(conv.link)
    assert r.status_code == 200 and "joana@exemplo.org" in r.text
    assert 'name="email"' not in r.text
    for campo in ("nome", "cpf", "telefone", "justificativa", "consentimento"):
        assert f'name="{campo}"' in r.text
    for campo in ("nome", "cpf", "telefone"):
        assert re.search(rf'<input id="{campo}" name="{campo}"[^>]*value=""', r.text), campo
    assert "Aviso de privacidade" in r.text


def test_link_invalido(amb):
    assert amb.client.get("/convite/nada").status_code == 410


def test_preencher_envia_para_aprovacao(conv):
    r = _preencher(conv, email="outro@x.org")
    assert r.status_code == 200 and "Recebemos sua solicitação" in r.text
    sol = conv.banco.obter(conv.sid)
    assert (sol["status"], sol["email"], sol["uid_sugerido"], sol["organizacao"]) == \
        ("pendente", "joana@exemplo.org", "joanalima", "CLIENTE-A")
    assert sol["nome"] == "Joana Pereira Lima" and sol["confirmado_em"]
    assert conv.banco.consentimento(conv.sid)["email_confirmado_em"]
    assert conv.client.post(conv.link, data=PREENCHE).status_code == 410
    novo = conv.correio.enviados[conv.enviados_antes:]
    assert [m["para"] for m in novo] == ["admin@teste.local"]
    assert "convite_preenchido" in [a["acao"] for a in auditoria(conv.banco)]


def test_preencher_expira_so_pedido_anterior_do_mesmo_cpf_e_email(conv):
    antigo = conv.banco.criar_solicitacao(
        {"nome": "Joana Pereira Lima", "cpf": "12345678909", "email": "joana@exemplo.org",
         "telefone": "+5511987654321", "justificativa": "x"},
        uid_sugerido="joanalima", ip="", user_agent="", versao_aviso="v", texto_aviso="t", agora=conv.relogio())
    outro_email = conv.banco.criar_solicitacao(
        {"nome": "Joana Pereira Lima", "cpf": "12345678909", "email": "j2@exemplo.org",
         "telefone": "+5511987654321", "justificativa": "x"},
        uid_sugerido="joanalima", ip="", user_agent="", versao_aviso="v", texto_aviso="t", agora=conv.relogio())
    assert conv.banco.obter(antigo)["status"] == "aguardando_confirmacao"
    _preencher(conv)
    assert conv.banco.obter(antigo)["status"] == "expirada"
    assert conv.banco.obter(outro_email)["status"] == "aguardando_confirmacao"
    assert conv.banco.obter(conv.sid)["status"] == "pendente"


def test_dado_invalido_nao_grava(conv):
    r = _preencher(conv, cpf="123")
    assert r.status_code == 400 and "CPF inválido" in r.text
    assert conv.banco.obter(conv.sid)["status"] == "convidado"


def test_sem_consentimento_nao_grava(conv):
    r = _preencher(conv, consentimento="")
    assert r.status_code == 400 and "aviso de privacidade" in r.text
    assert conv.banco.obter(conv.sid)["status"] == "convidado" and conv.banco.consentimento(conv.sid) is None
    assert conv.client.get(conv.link).status_code == 200


def test_convite_cancelado(conv):
    conv.banco.cancelar_convite(conv.sid, conv.relogio())
    assert conv.client.get(conv.link).status_code == 410
    assert _preencher(conv).status_code == 410


def test_preencher_nao_cria_conta_na_hora(conv):
    assert _preencher(conv).status_code == 200
    assert "joanalima" not in conv.dir.contas
    assert not any("/definir-senha/" in m["texto"] for m in conv.correio.enviados)


def test_reenviar_invalida_o_link_anterior(conv):
    assert conv.client.get(conv.link).status_code == 200
    _login(conv)
    assert conv.client.post(f"/admin/solicitacao/{conv.sid}/reenviar-convite").status_code == 302
    conv.client.post("/admin/sair")
    novo = conv.correio.caminho_do_link()
    assert novo != conv.link
    assert _preencher(conv).status_code == 410
    assert conv.client.post(novo, data=PREENCHE).status_code == 200


def test_aprovacao_pre_preenche_cliente_novo_do_convite(amb):
    import re
    from html import unescape
    amb.dir.contas["existente"] = dict(uid="existente", cn="E", mail="e@y", ou="CLIENTE-A", cpf="9", telefone="",
                                       senha=None)
    _login(amb)
    amb.client.post("/admin/convidar-por-email", data={
        "acao": "enviar", "email": ["joana@exemplo.org"], "organizacao": "__nova__",
        "organizacao_nova": "Cliente Novo", "confirmar_nova": "sim"})
    amb.client.post("/admin/sair")
    amb.client.post(amb.correio.caminho_do_link(), data=PREENCHE)
    [sol] = amb.banco.buscar("joana@exemplo.org", "pendente", 1)
    _login(amb)
    html = amb.client.get(f"/admin/solicitacao/{sol['id']}").text
    assert '<option value="__nova__" selected>' in html
    nova = re.search(r'name="organizacao_nova" value="([^"]*)"', html)
    assert nova and unescape(nova.group(1)) == "Cliente Novo"
    r = amb.client.post(f"/admin/solicitacao/{sol['id']}/aprovar", data={
        "organizacao": "__nova__", "organizacao_nova": unescape(nova.group(1)), "confirmar_nova": "sim",
        "uid": "joanalima"})
    assert r.status_code == 302 and amb.dir.contas["joanalima"]["ou"] == "Cliente Novo"


def test_aprovacao_cliente_existente_continua_selecionado(amb):
    amb.dir.contas["existente"] = dict(uid="existente", cn="E", mail="e@y", ou="CLIENTE-A", cpf="9", telefone="",
                                       senha=None)
    _login(amb)
    amb.client.post("/admin/convidar-por-email", data={"acao": "enviar", "email": ["joana@exemplo.org"],
                                                       "organizacao": "CLIENTE-A"})
    amb.client.post("/admin/sair")
    amb.client.post(amb.correio.caminho_do_link(), data=PREENCHE)
    [sol] = amb.banco.buscar("joana@exemplo.org", "pendente", 1)
    _login(amb)
    html = amb.client.get(f"/admin/solicitacao/{sol['id']}").text
    assert "<option selected>CLIENTE-A</option>" in html and '<option value="__nova__" selected>' not in html
