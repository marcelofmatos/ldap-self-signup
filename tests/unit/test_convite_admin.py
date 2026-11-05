import pytest

from app import tokens
from tests.fakes import auditoria
from tests.unit.test_admin import _login

CONVITE = {"nome": "Joana Pereira Lima", "cpf": "123.456.789-09", "email": "Joana@Exemplo.org",
           "telefone": "(11) 98765-4321", "organizacao": "CLIENTE-A", "uid": ""}


@pytest.fixture
def adm(amb):
    amb.dir.contas["existente"] = dict(uid="existente", cn="E", mail="e@y", ou="CLIENTE-A", cpf="9", telefone="",
                                       senha=None)
    _login(amb)
    return amb


def _convidar(amb, **over):
    return amb.client.post("/admin/convidar", data={**CONVITE, **over})


def _convidados(amb):
    return amb.banco.buscar("", "convidado", 1)


def _link_valido(amb, caminho):
    token = caminho.removeprefix("/convite/")
    return tokens.validar(amb.banco, token, tokens.CONVITE, amb.relogio()) is not None


def _acoes(amb, sid):
    return [(h["ator"], h["acao"], h["detalhe"]) for h in amb.banco.historico(sid)]


def test_convidar_exige_login(amb):
    for r in (amb.client.get("/admin/convidar"), amb.client.post("/admin/convidar", data=CONVITE),
              amb.client.post("/admin/solicitacao/1/reenviar-convite"),
              amb.client.post("/admin/solicitacao/1/cancelar-convite")):
        assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_formulario_de_convite(adm):
    r = adm.client.get("/admin/convidar")
    assert r.status_code == 200 and '<main class="largo">' in r.text
    for campo in ("nome", "cpf", "email", "telefone", "uid", "organizacao_nova"):
        assert f'name="{campo}"' in r.text, campo
    assert "<option>CLIENTE-A</option>" in r.text and 'value="__nova__"' in r.text
    assert 'href="/admin/convidar"' in adm.client.get("/admin/").text  # link no menu


def test_formulario_de_convite_ldap_fora(adm):
    adm.dir.falhar = True
    assert adm.client.get("/admin/convidar").status_code == 503


def test_convidar_cria_convite_e_envia_link(adm):
    r = _convidar(adm)
    [sol] = _convidados(adm)
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/admin/solicitacao/{sol['id']}")
    assert (sol["nome"], sol["cpf"], sol["email"], sol["telefone"]) == \
           ("Joana Pereira Lima", "12345678909", "joana@exemplo.org", "+5511987654321")
    assert (sol["origem"], sol["convidado_por"], sol["uid_sugerido"], sol["organizacao"], sol["link_enviado"]) == \
           ("convite", "chefe", "joanalima", "CLIENTE-A", 1)
    [email] = adm.correio.enviados
    assert email["para"] == "joana@exemplo.org" and "convite" in email["assunto"].lower()
    assert adm.correio.caminho_do_link().startswith("/convite/")
    assert "7 dias" in email["texto"] and "chefe" in email["texto"] and "Joana Pereira Lima" in email["texto"]
    assert _acoes(adm, sol["id"]) == [("chefe", "convite_criado", "uid=joanalima org=CLIENTE-A"),
                                      ("chefe", "convite_enviado", "joana@exemplo.org")]
    assert "joanalima" not in adm.dir.contas  # a conta só nasce no aceite


def test_convidar_com_uid_escolhido(adm):
    _convidar(adm, uid="JLima")
    assert _convidados(adm)[0]["uid_sugerido"] == "jlima"


def test_convidar_validacao(adm):
    r = _convidar(adm, cpf="123", email="x")
    assert r.status_code == 400 and "CPF inválido" in r.text and "E-mail inválido" in r.text
    assert 'value="Joana Pereira Lima"' in r.text
    assert _convidados(adm) == [] and adm.correio.enviados == []
    assert _convidar(adm, uid="1x").status_code == 400


def test_convidar_uid_em_uso_no_ldap(adm):
    r = _convidar(adm, uid="existente")
    assert r.status_code == 409 and "existente" in r.text and _convidados(adm) == []


def test_convidar_cpf_ou_email_existente_exige_outra_pessoa(adm):
    adm.dir.contas["jl"] = dict(uid="jl", cn="J", mail="joana@exemplo.org", ou="CLIENTE-A", cpf="0", telefone="",
                                senha=None)
    r = _convidar(adm)
    assert r.status_code == 409 and 'name="confirmar_outra_pessoa"' in r.text and _convidados(adm) == []
    assert _convidar(adm, confirmar_outra_pessoa="sim").status_code == 302 and len(_convidados(adm)) == 1


def test_convidar_cliente_novo_exige_confirmacao(adm):
    assert _convidar(adm, organizacao="__nova__", organizacao_nova="NOVA").status_code == 400
    assert _convidar(adm, organizacao="").status_code == 400
    assert _convidados(adm) == []
    r = _convidar(adm, organizacao="__nova__", organizacao_nova="NOVA", confirmar_nova="sim")
    assert r.status_code == 302 and _convidados(adm)[0]["organizacao"] == "NOVA"


def test_novo_convite_do_mesmo_cpf_substitui_o_anterior(adm):
    _convidar(adm)
    antigo = _convidados(adm)[0]["id"]
    link_antigo = adm.correio.caminho_do_link()
    _convidar(adm, email="joana2@exemplo.org")
    [novo] = _convidados(adm)
    assert novo["id"] != antigo and adm.banco.obter(antigo)["status"] == "expirada"
    assert not _link_valido(adm, link_antigo)
    assert _link_valido(adm, adm.correio.caminho_do_link())
    assert _acoes(adm, antigo)[-1] == ("chefe", "convite_cancelado", f"substituído pelo convite #{novo['id']}")


def test_falha_de_smtp_e_reenviar_convite(adm):
    adm.correio.falhar = True
    assert _convidar(adm).status_code == 302
    [sol] = _convidados(adm)
    assert sol["link_enviado"] == 0 and _acoes(adm, sol["id"])[-1][1] == "falha_envio_convite"
    r = adm.client.get(f"/admin/solicitacao/{sol['id']}")
    assert "link não enviado" in r.text and '<tr class="erro">' in r.text
    assert "link não enviado" in adm.client.get("/admin/?status=convidado").text
    adm.correio.falhar = False
    r = adm.client.post(f"/admin/solicitacao/{sol['id']}/reenviar-convite")
    assert r.status_code == 302 and adm.banco.obter(sol["id"])["link_enviado"] == 1
    assert _acoes(adm, sol["id"])[-1] == ("chefe", "convite_enviado", "joana@exemplo.org")


def test_reenviar_convite_invalida_o_link_anterior(adm):
    _convidar(adm)
    sid = _convidados(adm)[0]["id"]
    primeiro = adm.correio.caminho_do_link()
    adm.client.post(f"/admin/solicitacao/{sid}/reenviar-convite")
    assert not _link_valido(adm, primeiro)
    assert _link_valido(adm, adm.correio.caminho_do_link())


def test_cancelar_convite(adm):
    _convidar(adm)
    sid = _convidados(adm)[0]["id"]
    link = adm.correio.caminho_do_link()
    r = adm.client.post(f"/admin/solicitacao/{sid}/cancelar-convite")
    assert r.status_code == 302 and adm.banco.obter(sid)["status"] == "expirada"
    assert not _link_valido(adm, link)
    assert _acoes(adm, sid)[-1] == ("chefe", "convite_cancelado", "")
    assert adm.client.post(f"/admin/solicitacao/{sid}/cancelar-convite").status_code == 409
    assert adm.client.post(f"/admin/solicitacao/{sid}/reenviar-convite").status_code == 409


def test_detalhe_do_convite(adm):
    _convidar(adm)
    sid = _convidados(adm)[0]["id"]
    r = adm.client.get(f"/admin/solicitacao/{sid}")
    assert '<span class="pill st-convidado">Convidado</span>' in r.text
    assert "Convite (por chefe)" in r.text and "joanalima" in r.text and "CLIENTE-A" in r.text
    assert f'action="/admin/solicitacao/{sid}/reenviar-convite"' in r.text
    assert f'action="/admin/solicitacao/{sid}/cancelar-convite"' in r.text
    assert "convite_criado" in r.text


def test_detalhe_da_solicitacao_do_formulario_mostra_origem(adm):
    from tests.unit.test_admin import _pendente
    sid = _pendente(adm)
    r = adm.client.get(f"/admin/solicitacao/{sid}")
    assert "Formulário" in r.text and "reenviar-convite" not in r.text


def test_lista_tem_badge_e_pilula_de_convidado(adm):
    _convidar(adm)
    r = adm.client.get("/admin/?status=todos")
    assert '<span class="pill st-convidado">Convidado</span>' in r.text
    assert 'Convidado <span class="contagem">1</span>' in r.text
    assert ".st-convidado{" in r.text
    assert "Joana" in adm.client.get("/admin/?q=chefe&status=todos").text


def test_tema_exemplo_tem_pilula_de_convidado():
    from pathlib import Path
    base = Path(__file__).resolve().parents[2] / "templates-exemplo" / "exemplo" / "paginas" / "base.html"
    assert ".st-convidado{" in base.read_text(encoding="utf-8")


def test_convidar_uid_reservado_por_outro_convite_em_aberto(adm):
    _convidar(adm)
    [primeiro] = _convidados(adm)
    r = _convidar(adm, cpf="987.654.321-00", email="outra@exemplo.org")  # mesmo uid derivado: joanalima
    assert r.status_code == 409 and f"convite #{primeiro['id']}" in r.text
    assert [s["id"] for s in _convidados(adm)] == [primeiro["id"]]
    assert _convidar(adm, cpf="987.654.321-00", email="outra@exemplo.org", uid="joanalima2").status_code == 302
