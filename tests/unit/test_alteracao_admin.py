from datetime import datetime, timezone

import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login


@pytest.fixture
def adm(amb):
    _login(amb)
    return amb


def _alteracao(amb, **dados):
    amb.dir.contas["mariasouza"] = dict(uid="mariasouza", cn="Maria Souza", mail="maria@exemplo.org", ou="CLIENTE-A",
                                        cpf="52998224725", telefone="+5511912345678", senha=None, grupos=[])
    base = {"nome": "Maria Souza", "cpf": "52998224725", "email": "maria@exemplo.org",
            "telefone": "+5521998765432", "justificativa": ""}
    base.update(dados)
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua",
                agora=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc), email_confirmado=False)
    return amb.banco.criar_alteracao(base, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons)


def test_detalhe_mostra_atual_e_novo(adm):
    sid = _alteracao(adm)
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert "Alteração de dados" in html and "(11) 91234-5678" in html and "(21) 99876-5432" in html
    assert 'name="uid"' not in html and 'name="organizacao"' not in html
    assert "já existe" not in html.lower()  # a própria conta não é conflito
    assert "O link para definir a senha irá para o e-mail novo." not in html


def test_detalhe_avisa_que_link_vai_para_email_novo(adm):
    sid = _alteracao(adm, email="nova@exemplo.org")
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert "O link para definir a senha irá para o e-mail novo." in html


def test_detalhe_destaca_so_o_que_muda_de_fato(adm):
    sid = _alteracao(adm, nome="Maria da Silva Souza")  # cn derivado = "Maria Souza": nome igual
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert "<strong>+55 (21) 99876-5432</strong>" in html
    assert "<strong>Maria da Silva Souza</strong>" not in html and "Maria da Silva Souza" in html
    assert "<strong>529.982.247-25</strong>" not in html


def test_lista_marca_alteracao(adm):
    _alteracao(adm)
    assert '<span class="pill st-alteracao">alteração</span>' in adm.client.get("/admin/").text


def test_aprovar_atualiza_ldap_e_envia_link_ao_email_novo(adm):
    sid = _alteracao(adm, email="nova@exemplo.org")
    r = adm.client.post(f"/admin/solicitacao/{sid}/aprovar")
    assert r.status_code == 302
    conta = adm.dir.contas["mariasouza"]
    assert conta["telefone"] == "+5521998765432" and conta["mail"] == "nova@exemplo.org"
    sol = adm.banco.obter(sid)
    assert sol["status"] == "aprovada" and sol["uid_final"] == "mariasouza" and sol["link_enviado"] == 1
    assert adm.correio.enviados[-1]["para"] == "nova@exemplo.org"
    assert "/definir-senha/" in adm.correio.enviados[-1]["texto"]
    assert "dados foram atualizados" in adm.correio.enviados[-1]["texto"]


def test_reenviar_alteracao_usa_modelo_dados_atualizados(adm):
    sid = _alteracao(adm)
    adm.client.post(f"/admin/solicitacao/{sid}/aprovar")
    adm.client.post(f"/admin/solicitacao/{sid}/reenviar")
    assert "dados foram atualizados" in adm.correio.enviados[-1]["texto"]


def test_aprovar_com_cpf_de_outra_conta_exige_confirmacao(adm):
    adm.dir.contas["outra"] = dict(uid="outra", cn="Outra Pessoa", mail="o@exemplo.org", ou="", cpf="11144477735",
                                   telefone="", senha=None, grupos=[])
    sid = _alteracao(adm, cpf="11144477735")
    assert adm.client.post(f"/admin/solicitacao/{sid}/aprovar").status_code == 409
    assert adm.dir.contas["mariasouza"]["cpf"] == "52998224725"
    r = adm.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"confirmar_outra_pessoa": "sim"})
    assert r.status_code == 302 and adm.dir.contas["mariasouza"]["cpf"] == "11144477735"


def test_aprovar_erro_ldap_volta_para_pendente(adm):
    sid = _alteracao(adm)
    adm.dir.falhar_criacao = True
    assert adm.client.post(f"/admin/solicitacao/{sid}/aprovar").status_code == 503
    assert adm.banco.obter(sid)["status"] == "pendente"
    assert any(a["acao"] == "erro_ldap" for a in auditoria(adm.banco))


def test_aprovar_conta_sumiu(adm):
    sid = _alteracao(adm)
    del adm.dir.contas["mariasouza"]
    assert adm.client.post(f"/admin/solicitacao/{sid}/aprovar").status_code == 409
    assert adm.banco.obter(sid)["status"] == "pendente"
    assert adm.correio.enviados == []
    assert any(a["acao"] == "aprovacao_bloqueada" for a in auditoria(adm.banco))


def test_aprovar_com_solicitacao_ja_reivindicada_da_409_e_nao_altera_ldap(adm):
    sid = _alteracao(adm)
    assert adm.banco.reivindicar(sid)
    assert adm.client.post(f"/admin/solicitacao/{sid}/aprovar").status_code == 409
    assert adm.dir.contas["mariasouza"]["telefone"] == "+5511912345678"


def test_aprovando_mostra_orientacao_de_alteracao(adm):
    sid = _alteracao(adm)
    adm.banco.reivindicar(sid)
    html = adm.client.get(f"/admin/solicitacao/{sid}").text
    assert "reaplicar a alteração é seguro" in html and "se a conta foi criada" not in html


def test_destravar_alteracao_volta_para_pendente(adm):
    sid = _alteracao(adm)
    adm.banco.reivindicar(sid)
    assert adm.client.post(f"/admin/solicitacao/{sid}/destravar").status_code == 302
    assert adm.banco.obter(sid)["status"] == "pendente"


def test_detalhe_decidido_nao_consulta_ldap(adm):
    aprovada = _alteracao(adm)
    adm.client.post(f"/admin/solicitacao/{aprovada}/aprovar")
    rejeitada = _alteracao(adm)
    adm.client.post(f"/admin/solicitacao/{rejeitada}/rejeitar")
    adm.dir.falhar = True
    for sid in (aprovada, rejeitada):
        assert adm.client.get(f"/admin/solicitacao/{sid}").status_code == 200
    assert "Atual (LDAP)" not in adm.client.get(f"/admin/solicitacao/{aprovada}").text


def test_rejeitar_nao_muda_ldap(adm):
    sid = _alteracao(adm)
    adm.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"motivo": "telefone errado"})
    assert adm.banco.obter(sid)["status"] == "rejeitada"
    assert adm.dir.contas["mariasouza"]["telefone"] == "+5511912345678"


def test_rejeitar_alteracao_avisa_o_email_do_ldap_e_nao_o_novo(adm):
    sid = _alteracao(adm, email="nova@exemplo.org")
    adm.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"motivo": "telefone errado", "avisar": "sim"})
    enviado = adm.correio.enviados[-1]
    assert enviado["para"] == "maria@exemplo.org"
    assert "correção de dados não aceita" in enviado["assunto"]
    assert "telefone errado" in enviado["texto"]
    assert all(e["para"] != "nova@exemplo.org" for e in adm.correio.enviados)


def test_rejeitar_alteracao_com_ldap_fora_rejeita_e_audita_falha_do_aviso(adm):
    sid = _alteracao(adm, email="nova@exemplo.org")
    adm.dir.falhar = True
    adm.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"avisar": "sim"})
    assert adm.banco.obter(sid)["status"] == "rejeitada"
    assert adm.correio.enviados == []
    assert any(a["acao"] == "falha_envio_aviso" for a in auditoria(adm.banco))
