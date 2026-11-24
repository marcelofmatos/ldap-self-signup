"""Ação "Atualizar conta existente" no detalhe de uma solicitação com conflito no LDAP."""
from datetime import datetime, timezone

import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login, _pendente

SECAO = "Atualizar conta existente"


@pytest.fixture
def adm(amb):
    _login(amb)
    return amb


def _conta(amb, uid, **dados):
    base = dict(uid=uid, cn="Maria Antiga", mail="antiga@exemplo.org", ou="CLIENTE-A", cpf="11144477735",
                telefone="+5511900000000", senha="Antiga#123", grupos=["Equipe"])
    base.update(dados)
    amb.dir.contas[uid] = base


def _mesma_pessoa(amb):
    """Conta msouza com o CPF e o e-mail da solicitação: o único candidato, sem conflito com outra conta."""
    _conta(amb, "msouza", cpf="52998224725", mail="maria@exemplo.org")
    _conta(amb, "outra", cpf="00000000191", mail="outra@exemplo.org", ou="CLIENTE-B")  # cliente CLIENTE-B existe
    return _pendente(amb)


def _form_atualizar(html):
    """Trecho do formulário de atualizar conta (vazio se não houver)."""
    if "/atualizar-conta" not in html:
        return ""
    return html.split("/atualizar-conta", 1)[1].split("</form>", 1)[0]


def _atualizar(amb, sid, **dados):
    return amb.client.post(f"/admin/solicitacao/{sid}/atualizar-conta", data=dados)


def test_sem_conflito_nao_mostra_a_secao(adm):
    sid = _pendente(adm)
    assert SECAO not in adm.client.get(f"/admin/solicitacao/{sid}").text


def test_com_conflito_mostra_a_secao(adm):
    sid = _mesma_pessoa(adm)
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert SECAO in html and f"/admin/solicitacao/{sid}/atualizar-conta" in html
    assert "Atualizar conta existente e avisar" in html


def test_secao_some_fora_de_pendente(adm):
    sid = _mesma_pessoa(adm)
    adm.banco.rejeitar(sid, "", "chefe", "2026-11-04T12:00:00+00:00")
    assert SECAO not in adm.client.get(f"/admin/solicitacao/{sid}").text


def test_secao_some_em_alteracao(adm):
    _conta(adm, "mariasouza", cpf="52998224725", mail="maria@exemplo.org")
    _conta(adm, "outra", cpf="52998224725", mail="outra@exemplo.org")  # conflito de CPF com outra conta
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua",
                agora=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc), email_confirmado=False)
    sid = adm.banco.criar_alteracao({"nome": "Maria Souza", "cpf": "52998224725", "email": "maria@exemplo.org",
                                     "telefone": "+5521998765432", "justificativa": ""},
                                    uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons)
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert "já existe" in html.lower() and SECAO not in html


def test_um_candidato_fica_fixo(adm):
    sid = _mesma_pessoa(adm)
    form = _form_atualizar(adm.client.get(f"/admin/solicitacao/{sid}").text)
    assert 'type="hidden" name="uid_conta" value="msouza"' in form and 'type="radio"' not in form
    assert 'name="confirmar_outra_pessoa"' not in form  # CPF e e-mail estão na própria conta escolhida


def test_varios_candidatos_viram_radio(adm):
    _conta(adm, "mariasouza", cpf="11144477735", mail="a@exemplo.org")  # mesmo uid
    _conta(adm, "msouza", cpf="52998224725", mail="b@exemplo.org")  # mesmo CPF
    _conta(adm, "outra", cpf="00000000191", mail="maria@exemplo.org")  # mesmo e-mail
    sid = _pendente(adm)
    form = _form_atualizar(adm.client.get(f"/admin/solicitacao/{sid}").text)
    for uid in ("mariasouza", "msouza", "outra"):
        assert f'type="radio" name="uid_conta" value="{uid}"' in form
    assert form.count('name="uid_conta"') == 3 and 'type="hidden" name="uid_conta"' not in form
    assert 'name="confirmar_outra_pessoa"' in form and "Confirmo que é outra pessoa" in form


def test_comparacao_mostra_atual_e_novo(adm):
    sid = _mesma_pessoa(adm)
    form = _form_atualizar(adm.client.get(f"/admin/solicitacao/{sid}").text)
    assert "Maria Antiga" in form and "<strong>Maria da Silva Souza</strong>" in form
    assert "+55 (11) 90000-0000" in form and "<strong>+55 (11) 91234-5678</strong>" in form
    assert "<strong>maria@exemplo.org</strong>" not in form  # e-mail igual não é destacado
    assert "Cliente" in form and "CLIENTE-A" in form


def test_cliente_pre_selecionado_com_o_ou_da_conta(adm):
    sid = _mesma_pessoa(adm)
    form = _form_atualizar(adm.client.get(f"/admin/solicitacao/{sid}").text)
    assert "<option selected>CLIENTE-A</option>" in form


def test_cliente_pre_selecionado_com_o_da_solicitacao(adm):
    sid = _mesma_pessoa(adm)
    adm.banco.atualizar(sid, organizacao="CLIENTE-B")
    form = _form_atualizar(adm.client.get(f"/admin/solicitacao/{sid}").text)
    assert "<option selected>CLIENTE-B</option>" in form


def test_dois_seletores_de_cliente_sem_ids_repetidos(adm):
    sid = _mesma_pessoa(adm)
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    for id_ in ("organizacao", "organizacao_nova", "uid"):
        assert html.count(f'id="{id_}"') == 1
    form = _form_atualizar(html)
    assert 'name="organizacao"' in form and 'name="organizacao_nova"' in form and 'name="confirmar_nova"' in form
    assert html.count('<div class="cliente-novo">') == 2
    script = html.split("<script>", 1)[1]
    assert "querySelectorAll('.cliente-novo')" in script  # o script trata cada formulário à parte


def test_uid_conta_adulterado_recusado(adm):
    sid = _mesma_pessoa(adm)
    r = _atualizar(adm, sid, uid_conta="outra", organizacao="CLIENTE-A")
    assert r.status_code == 400 and adm.dir.contas["outra"]["cpf"] == "00000000191"
    assert adm.banco.obter(sid)["status"] == "pendente"


def test_conflito_com_outra_conta_exige_confirmacao(adm):
    _conta(adm, "msouza", cpf="52998224725", mail="b@exemplo.org")
    _conta(adm, "outra", cpf="00000000191", mail="maria@exemplo.org")
    sid = _pendente(adm)
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A")
    assert r.status_code == 409 and "Confirme que é outra pessoa" in r.text
    assert adm.dir.contas["msouza"]["mail"] == "b@exemplo.org"
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A", confirmar_outra_pessoa="sim",
                   confirmar_email_novo="sim")
    assert r.status_code == 302 and adm.dir.contas["msouza"]["mail"] == "maria@exemplo.org"


def test_cliente_novo_exige_confirmacao(adm):
    sid = _mesma_pessoa(adm)
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="__nova__", organizacao_nova="NOVA")
    assert r.status_code == 400 and adm.dir.contas["msouza"]["ou"] == "CLIENTE-A"
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="__nova__", organizacao_nova="NOVA",
                   confirmar_nova="sim")
    assert r.status_code == 302 and adm.dir.contas["msouza"]["ou"] == "NOVA"


def test_atualiza_a_conta_e_avisa(adm):
    sid = _mesma_pessoa(adm)
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-B")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/admin/solicitacao/{sid}")
    conta = adm.dir.contas["msouza"]
    assert (conta["cn"], conta["cpf"], conta["mail"], conta["telefone"], conta["ou"]) == \
           ("Maria Souza", "52998224725", "maria@exemplo.org", "+5511912345678", "CLIENTE-B")
    assert conta["grupos"] == ["Equipe"] and conta["senha"] == "Antiga#123"
    sol = adm.banco.obter(sid)
    assert (sol["status"], sol["uid_final"], sol["organizacao"], sol["decidido_por"], sol["link_enviado"]) == \
           ("aprovada", "msouza", "CLIENTE-B", "chefe", 1)
    acoes = [a["acao"] for a in auditoria(adm.banco)]
    assert acoes[:2] == ["link_enviado", "conta_atualizada"]
    email = adm.correio.enviados[-1]
    assert email["para"] == "maria@exemplo.org" and "/definir-senha/" in email["texto"]
    assert "msouza" in adm.client.get(r.headers["Location"]).text


def test_falha_do_envio_registrada(adm):
    sid = _mesma_pessoa(adm)
    adm.correio.falhar = True
    assert _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A").status_code == 302
    assert adm.banco.obter(sid)["link_enviado"] == 0
    assert auditoria(adm.banco)[0]["acao"] == "falha_envio_link"


def test_falha_no_ldap_volta_a_pendente(adm):
    sid = _mesma_pessoa(adm)
    adm.dir.falhar_criacao = True
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A")
    assert r.status_code == 503 and "indisponível" in r.text
    assert adm.banco.obter(sid)["status"] == "pendente" and adm.dir.contas["msouza"]["cn"] == "Maria Antiga"
    assert auditoria(adm.banco)[0]["acao"] == "erro_ldap"


def test_solicitacao_nao_pendente_recusada(adm):
    sid = _mesma_pessoa(adm)
    adm.banco.reivindicar(sid)
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A")
    assert r.status_code == 409 and adm.dir.contas["msouza"]["cn"] == "Maria Antiga"


def test_alteracao_recusada(adm):
    _conta(adm, "mariasouza", cpf="52998224725", mail="maria@exemplo.org")
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua",
                agora=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc), email_confirmado=False)
    sid = adm.banco.criar_alteracao({"nome": "Maria Souza", "cpf": "52998224725", "email": "maria@exemplo.org",
                                     "telefone": "+5521998765432", "justificativa": ""},
                                    uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons)
    r = _atualizar(adm, sid, uid_conta="mariasouza", organizacao="CLIENTE-A")
    assert r.status_code == 400 and adm.banco.obter(sid)["status"] == "pendente"


def test_exige_login(amb):
    sid = _mesma_pessoa(amb)
    r = _atualizar(amb, sid, uid_conta="msouza", organizacao="CLIENTE-A")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]
    assert amb.dir.contas["msouza"]["cn"] == "Maria Antiga"


def test_reenviar_apos_atualizar_usa_conta_atualizada(adm):
    sid = _mesma_pessoa(adm)
    _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A")
    assert adm.client.post(f"/admin/solicitacao/{sid}/reenviar").status_code == 302
    email = adm.correio.enviados[-1]
    assert "sua conta foi atualizada" in email["assunto"] and "/definir-senha/" in email["texto"]


def test_reenviar_apos_aprovar_continua_conta_aprovada(adm):
    sid = _pendente(adm)
    adm.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert adm.client.post(f"/admin/solicitacao/{sid}/reenviar").status_code == 302
    assert "sua conta foi aprovada" in adm.correio.enviados[-1]["assunto"]


AVISO_EMAIL = "Confirme a identidade da pessoa por outro canal antes de atualizar"


@pytest.mark.parametrize("mail_atual", ["antiga@exemplo.org", ""])
def test_email_diferente_exige_confirmacao(adm, mail_atual):
    _conta(adm, "mariasouza", cpf="11144477735", mail=mail_atual)  # mesmo uid, outro e-mail (ou nenhum)
    sid = _pendente(adm)
    form = _form_atualizar(adm.client.get(f"/admin/solicitacao/{sid}").text)
    assert AVISO_EMAIL in form and "O e-mail da solicitação (maria@exemplo.org) é diferente" in form
    assert 'name="confirmar_email_novo"' in form and "Confirmei a identidade da pessoa e o novo e-mail" in form
    enviados = len(adm.correio.enviados)
    r = _atualizar(adm, sid, uid_conta="mariasouza", organizacao="CLIENTE-A")
    assert r.status_code == 409 and adm.dir.contas["mariasouza"]["mail"] == mail_atual
    assert adm.banco.obter(sid)["status"] == "pendente" and len(adm.correio.enviados) == enviados
    r = _atualizar(adm, sid, uid_conta="mariasouza", organizacao="CLIENTE-A", confirmar_email_novo="sim")
    assert r.status_code == 302 and adm.dir.contas["mariasouza"]["mail"] == "maria@exemplo.org"


def test_email_igual_sem_maiusculas_nao_pede_confirmacao(adm):
    _conta(adm, "msouza", cpf="52998224725", mail="Maria@Exemplo.ORG")
    sid = _pendente(adm)
    form = _form_atualizar(adm.client.get(f"/admin/solicitacao/{sid}").text)
    assert AVISO_EMAIL not in form and 'name="confirmar_email_novo"' not in form
    assert _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A").status_code == 302


def test_conta_admin_nao_e_oferecida_nem_aceita(adm):
    _conta(adm, "chefe", cpf="52998224725", mail="maria@exemplo.org")  # chefe é admin no FakeDiretorio
    sid = _pendente(adm)
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert SECAO in html and "Conta de administrador: atualize manualmente" in html
    assert "/atualizar-conta" not in html and 'name="uid_conta"' not in html
    r = _atualizar(adm, sid, uid_conta="chefe", organizacao="CLIENTE-A")
    assert r.status_code == 403 and adm.dir.contas["chefe"]["cn"] == "Maria Antiga"
    assert adm.banco.obter(sid)["status"] == "pendente"


def test_conta_admin_entre_varias_fica_sem_radio(adm):
    _conta(adm, "chefe", cpf="52998224725", mail="x@exemplo.org")
    _conta(adm, "msouza", cpf="11144477735", mail="maria@exemplo.org")
    sid = _pendente(adm)
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert "Conta de administrador: atualize manualmente" in html
    form = _form_atualizar(html)
    assert 'value="chefe"' not in form and 'type="hidden" name="uid_conta" value="msouza"' in form


def test_conta_que_deixou_de_existir_recusada(adm, monkeypatch):
    sid = _mesma_pessoa(adm)
    assert "/atualizar-conta" in adm.client.get(f"/admin/solicitacao/{sid}").text
    enviados = len(adm.correio.enviados)
    # removida entre o GET e o POST: a busca de conflitos ainda a acha, a leitura da conta não
    original = adm.dir.obter_conta
    monkeypatch.setattr(adm.dir, "obter_conta", lambda uid: None if uid == "msouza" else original(uid))
    r = _atualizar(adm, sid, uid_conta="msouza", organizacao="CLIENTE-A", confirmar_email_novo="sim")
    assert r.status_code == 409 and "A conta msouza não existe mais no LDAP." in r.text
    assert adm.banco.obter(sid)["status"] == "pendente" and len(adm.correio.enviados) == enviados
    assert auditoria(adm.banco)[0]["acao"] == "aprovacao_bloqueada"
