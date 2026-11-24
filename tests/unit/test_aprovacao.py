import pytest

from app import aprovacao
from app.diretorio import ErroDiretorio
from tests.fakes import auditoria

DADOS = {"nome": "Joana Pereira Lima", "cpf": "12345678909", "email": "joana@exemplo.org",
         "telefone": "+5511987654321"}


def _pendente(amb):
    sid = amb.banco.criar_solicitacao({**DADOS, "justificativa": "Equipe."}, uid_sugerido="joanalima", ip="",
                                      user_agent="", versao_aviso="v1", texto_aviso="t", agora=amb.relogio())
    amb.banco.confirmar_email(sid, amb.relogio())
    return sid


def test_aprovar_cria_conta_e_registra(amb):
    sid = _pendente(amb)
    with amb.app.app_context():
        uid_number = aprovacao.aprovar(amb.app.extensions["signup"], sid, uid="joanalima",
                                       org="CLIENTE-A", ator="chefe")
    assert uid_number > 0 and amb.dir.contas["joanalima"]["ou"] == "CLIENTE-A"
    sol = amb.banco.obter(sid)
    assert (sol["status"], sol["uid_final"], sol["organizacao"], sol["decidido_por"]) == \
           ("aprovada", "joanalima", "CLIENTE-A", "chefe")
    [ultimo] = auditoria(amb.banco)[:1]
    assert (ultimo["ator"], ultimo["acao"]) == ("chefe", "aprovar") and "uid=joanalima org=CLIENTE-A" in ultimo["detalhe"]


def test_aprovar_erro_ldap_volta_ao_status_de_origem(amb):
    sid = _pendente(amb)
    amb.dir.falhar_criacao = True
    with amb.app.app_context(), pytest.raises(ErroDiretorio):
        aprovacao.aprovar(amb.app.extensions["signup"], sid, uid="joanalima", org="CLIENTE-A",
                          ator="chefe")
    assert amb.banco.obter(sid)["status"] == "pendente" and "joanalima" not in amb.dir.contas
    assert auditoria(amb.banco)[0]["acao"] == "erro_ldap"


def test_aprovar_ja_reivindicada(amb):
    sid = _pendente(amb)
    amb.banco.reivindicar(sid)
    with amb.app.app_context(), pytest.raises(aprovacao.JaReivindicada):
        aprovacao.aprovar(amb.app.extensions["signup"], sid, uid="joanalima", org="CLIENTE-A",
                          ator="chefe")
    assert "joanalima" not in amb.dir.contas


def test_atualizar_conta_existente_ok(amb):
    sid = _pendente(amb)
    amb.dir.contas["joanalima"] = {"uid": "joanalima", "cn": "Joana", "mail": "velho@exemplo.org", "ou": "CLIENTE-A",
                                   "cpf": "", "telefone": ""}
    with amb.app.app_context():
        aprovacao.atualizar_conta_existente(amb.app.extensions["signup"], sid, uid="joanalima",
                                            org="CLIENTE-B", ator="chefe")
    assert amb.dir.contas["joanalima"]["ou"] == "CLIENTE-B" and amb.dir.contas["joanalima"]["mail"] == "joana@exemplo.org"
    sol = amb.banco.obter(sid)
    assert (sol["status"], sol["uid_final"], sol["decidido_por"]) == ("aprovada", "joanalima", "chefe")
    ultimo = auditoria(amb.banco)[0]
    assert ultimo["acao"] == "conta_atualizada" and ultimo["detalhe"] == "uid=joanalima org=CLIENTE-B"


def test_atualizar_conta_existente_ja_reivindicada(amb):
    sid = _pendente(amb)
    amb.banco.reivindicar(sid)
    with amb.app.app_context(), pytest.raises(aprovacao.JaReivindicada):
        aprovacao.atualizar_conta_existente(amb.app.extensions["signup"], sid, uid="joanalima",
                                            org="CLIENTE-B", ator="chefe")


def test_atualizar_conta_existente_erro_ldap_volta_a_pendente(amb):
    sid = _pendente(amb)
    with amb.app.app_context(), pytest.raises(ErroDiretorio):
        aprovacao.atualizar_conta_existente(amb.app.extensions["signup"], sid, uid="naoexiste",
                                            org="CLIENTE-B", ator="chefe")
    assert amb.banco.obter(sid)["status"] == "pendente"
    ultimo = auditoria(amb.banco)[0]
    assert ultimo["acao"] == "erro_ldap" and ultimo["detalhe"].startswith("conta existente uid=naoexiste: ")
