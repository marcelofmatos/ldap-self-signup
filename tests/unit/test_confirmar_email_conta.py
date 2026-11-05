from datetime import timedelta

from app import tokens
from tests.fakes import auditoria

NOVO = "novo@exemplo.org"


def _preparar(amb, uid="ana", mail="", pendente=NOVO):
    amb.dir.contas[uid] = dict(uid=uid, cn="Ana Lima", mail=mail, ou="CLIENTE-A", cpf="52998224725",
                               telefone="", senha=None)
    agora = amb.relogio()
    if pendente:
        amb.banco.gravar_email_pendente(uid, pendente, "chefe", agora)
    token = tokens.emitir(amb.banco, tokens.DEFINIR_EMAIL, uid, 24, agora)
    return f"/confirmar-email-conta/{token}"


def test_banco_email_pendente(amb):
    assert amb.banco.email_pendente("ana") is None
    amb.banco.gravar_email_pendente("ana", "a@exemplo.org", "chefe", amb.relogio())
    amb.banco.gravar_email_pendente("ana", NOVO, "outro", amb.relogio())
    p = amb.banco.email_pendente("ana")
    assert p["email"] == NOVO and p["pedido_por"] == "outro" and p["criado_em"]
    amb.banco.remover_email_pendente("ana")
    assert amb.banco.email_pendente("ana") is None


def test_novo_token_invalida_o_anterior(amb):
    antigo = _preparar(amb)
    novo = tokens.emitir(amb.banco, tokens.DEFINIR_EMAIL, "ana", 24, amb.relogio())
    assert amb.client.get(antigo).status_code == 410
    assert amb.client.get(f"/confirmar-email-conta/{novo}").status_code == 200


def test_get_mostra_email_e_conta_sem_consumir(amb):
    caminho = _preparar(amb)
    r = amb.client.get(caminho)
    assert r.status_code == 200 and NOVO in r.text and "ana" in r.text
    assert amb.dir.contas["ana"]["mail"] == ""
    assert amb.client.get(caminho).status_code == 200


def test_get_link_invalido_ou_sem_pendente(amb):
    assert amb.client.get("/confirmar-email-conta/nada").status_code == 410
    assert amb.client.get(_preparar(amb, pendente=None)).status_code == 410


def test_post_grava_mail_e_leva_a_definir_senha(amb):
    caminho = _preparar(amb)
    r = amb.client.post(caminho)
    assert r.status_code == 302 and r.headers["Location"].startswith("/definir-senha/")
    assert amb.dir.contas["ana"]["mail"] == NOVO
    assert amb.banco.email_pendente("ana") is None
    a = auditoria(amb.banco)[0]
    assert (a["ator"], a["acao"], a["alvo"], a["detalhe"]) == ("publico", "email_definido", "ana", NOVO)
    assert amb.client.get(r.headers["Location"]).status_code == 200
    assert amb.client.post(caminho).status_code == 410


def test_post_corrige_email_existente(amb):
    caminho = _preparar(amb, mail="velho@exemplo.org")
    assert amb.client.post(caminho).status_code == 302
    assert amb.dir.contas["ana"]["mail"] == NOVO


def test_post_link_expirado(amb):
    caminho = _preparar(amb)
    amb.relogio.avancar(hours=25)
    assert amb.client.post(caminho).status_code == 410
    assert amb.dir.contas["ana"]["mail"] == ""


def test_post_sem_pendente_410(amb):
    assert amb.client.post(_preparar(amb, pendente=None)).status_code == 410


def test_post_conta_sumiu_410(amb):
    caminho = _preparar(amb)
    del amb.dir.contas["ana"]
    assert amb.client.post(caminho).status_code == 410


def test_post_ldap_fora_503_mantem_token(amb):
    caminho = _preparar(amb)
    amb.dir.falhar = True
    assert amb.client.post(caminho).status_code == 503
    amb.dir.falhar = False
    assert amb.banco.email_pendente("ana") is not None
    assert amb.client.post(caminho).status_code == 302
    assert amb.dir.contas["ana"]["mail"] == NOVO


def test_post_email_tomado_por_outra_conta_409(amb):
    caminho = _preparar(amb)
    amb.dir.contas["bia"] = dict(uid="bia", cn="Bia", mail=NOVO, ou="CLIENTE-A", cpf="1", telefone="", senha=None)
    r = amb.client.post(caminho)
    assert r.status_code == 409 and "bia" not in amb.dir.contas["ana"]["mail"]
    assert amb.dir.contas["ana"]["mail"] == ""
