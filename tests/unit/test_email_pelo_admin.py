import re

import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login

NOVO = "novo@exemplo.org"


def _conta(amb, uid="ana", mail=""):
    amb.dir.contas[uid] = dict(uid=uid, cn="Ana Lima", mail=mail, ou="CLIENTE-A", cpf="52998224725",
                               telefone="", senha=None, grupos=[])


@pytest.fixture
def adm(amb):
    _login(amb)
    _conta(amb)
    return amb


def _pedir(amb, email=NOVO, uid="ana"):
    return amb.client.post(f"/admin/contas/{uid}/email", data={"email": email})


def test_exige_login(amb):
    _conta(amb)
    r = _pedir(amb)
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]
    assert amb.banco.email_pendente("ana") is None


def test_pedido_envia_link_e_nao_muda_ldap(adm):
    r = _pedir(adm, " Novo@Exemplo.org ")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/contas/ana#email")
    assert adm.dir.contas["ana"]["mail"] == ""
    p = adm.banco.email_pendente("ana")
    assert p["email"] == NOVO and p["pedido_por"] == "chefe"
    [env] = adm.correio.enviados
    assert env["para"] == NOVO
    caminho = re.search(r"https://cadastro\.teste(/confirmar-email-conta/[^\s>]+)", env["texto"]).group(1)
    a = auditoria(adm.banco)[0]
    assert (a["ator"], a["acao"], a["alvo"], a["detalhe"]) == ("chefe", "email_solicitado", "ana", NOVO)
    # aceite 50: confirmar grava o mail e leva a definir senha
    r = adm.client.post(caminho)
    assert r.status_code == 302 and r.headers["Location"].startswith("/definir-senha/")
    assert adm.dir.contas["ana"]["mail"] == NOVO


def test_segundo_pedido_invalida_o_link_do_primeiro(adm):
    _pedir(adm)
    _pedir(adm, "outro@exemplo.org")
    links = [re.search(r"(/confirmar-email-conta/[^\s>]+)", e["texto"]).group(1) for e in adm.correio.enviados]
    assert adm.client.get(links[0]).status_code == 410
    assert adm.client.get(links[1]).status_code == 200
    assert adm.banco.email_pendente("ana")["email"] == "outro@exemplo.org"


def test_email_de_outra_conta_409(adm):
    _conta(adm, "bia", mail=NOVO)
    r = _pedir(adm)
    assert r.status_code == 409 and "bia" in r.text
    assert adm.banco.email_pendente("ana") is None and adm.correio.enviados == []


def test_email_invalido_nao_grava(adm):
    r = _pedir(adm, "isso-nao-e-email")
    assert r.status_code == 302
    assert adm.banco.email_pendente("ana") is None and adm.correio.enviados == []


def test_igual_ao_atual_sem_efeito(adm):
    adm.dir.contas["ana"]["mail"] = NOVO
    r = _pedir(adm)
    assert r.status_code == 302
    assert adm.banco.email_pendente("ana") is None and adm.correio.enviados == []
    assert "É o e-mail atual." in adm.client.get(r.headers["Location"]).text


def test_falha_smtp_desfaz_e_audita(adm):
    adm.correio.falhar = True
    r = _pedir(adm)
    assert r.status_code == 302
    assert adm.banco.email_pendente("ana") is None
    assert auditoria(adm.banco)[0]["acao"] == "falha_envio_email"
    assert "Falha ao enviar" in adm.client.get(r.headers["Location"]).text


def test_conta_inexistente_404(adm):
    assert _pedir(adm, uid="zzz").status_code == 404


def test_ldap_fora_503(adm):
    adm.dir.falhar = True
    assert _pedir(adm).status_code == 503


def test_ficha_mostra_form_e_pendente(adm):
    html = adm.client.get("/admin/contas/ana").text
    assert 'id="email"' in html and "sem e-mail" in html
    assert 'action="/admin/contas/ana/email"' in html
    _pedir(adm)
    html = adm.client.get("/admin/contas/ana").text
    assert "Aguardando confirmação de" in html and NOVO in html and "chefe" in html


def test_lista_linka_sem_email_para_a_ficha(adm):
    html = adm.client.get("/admin/contas").text
    assert '<a href="/admin/contas/ana#email"' in html


def test_rotulos_no_historico(adm):
    _pedir(adm)
    html = adm.client.get("/admin/contas/ana").text
    assert "Pediu confirmação de e-mail" in html


def test_ficha_ignora_pendente_com_link_expirado(adm):
    _pedir(adm)
    adm.relogio.avancar(hours=adm.cfg.token_ttl_hours + 1)
    assert "Aguardando confirmação" not in adm.client.get("/admin/contas/ana").text
