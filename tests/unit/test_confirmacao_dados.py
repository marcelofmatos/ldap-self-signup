import pytest

from app import tokens
from tests.fakes import auditoria
from tests.unit.test_admin import _login


def _conta(amb, uid="mariasouza", cn="Maria Souza", mail="maria@exemplo.org", ou="CLIENTE-A",
           cpf="52998224725", telefone="+5511912345678"):
    amb.dir.contas[uid] = dict(uid=uid, cn=cn, mail=mail, ou=ou, cpf=cpf, telefone=telefone, senha=None, grupos=[])


@pytest.fixture
def adm(amb):
    _login(amb)
    return amb


def test_confirmacao_individual_envia_email_com_link(adm):
    _conta(adm)
    r = adm.client.post("/admin/contas/mariasouza/confirmacao")
    assert r.status_code == 302
    assert adm.correio.enviados[-1]["para"] == "maria@exemplo.org"
    caminho = adm.correio.caminho_do_link()
    assert caminho.startswith("/confirmar-dados/")
    assert tokens.validar(adm.banco, caminho.rsplit("/", 1)[1], tokens.CONFIRMAR_DADOS, adm.relogio()) == "mariasouza"
    assert auditoria(adm.banco)[0]["acao"] == "confirmacao_dados"
    assert "m***@exemplo.org" in adm.client.get(r.headers["Location"]).text


def test_confirmacao_invalida_link_anterior(adm):
    _conta(adm)
    adm.client.post("/admin/contas/mariasouza/confirmacao")
    primeiro = adm.correio.caminho_do_link().rsplit("/", 1)[1]
    adm.client.post("/admin/contas/mariasouza/confirmacao")
    assert tokens.validar(adm.banco, primeiro, tokens.CONFIRMAR_DADOS, adm.relogio()) is None


def test_confirmacao_sem_email_nao_envia(adm):
    _conta(adm, mail="")
    adm.client.post("/admin/contas/mariasouza/confirmacao")
    assert adm.correio.enviados == []


def test_confirmacao_conta_inexistente_404(adm):
    assert adm.client.post("/admin/contas/naoexiste/confirmacao").status_code == 404


def test_confirmacao_exige_login(amb):
    _conta(amb)
    r = amb.client.post("/admin/contas/mariasouza/confirmacao")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


@pytest.mark.parametrize("rota", ["/admin/contas/confirmacao-lote/confirmar", "/admin/contas/confirmacao-lote"])
def test_lote_de_confirmacao_exige_login(amb, rota):
    r = amb.client.post(rota)
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_lista_tem_icone_de_confirmacao(adm):
    _conta(adm)
    _conta(adm, uid="semmail", mail="")
    html = adm.client.get("/admin/contas").text
    assert 'action="/admin/contas/mariasouza/confirmacao"' in html
    dica = "Pedir confirmação dos dados"
    assert f'class="icone" title="{dica}" aria-label="{dica}"><svg' in html
    assert 'action="/admin/contas/semmail/confirmacao"' in html
    assert 'disabled class="icone" title="Sem e-mail: cadastre o e-mail antes"' in html


def test_lote_de_confirmacao_pula_sem_email(adm):
    _conta(adm, uid="ana", mail="ana@exemplo.org")
    _conta(adm, uid="bia", mail="bia@exemplo.org")
    _conta(adm, uid="caio", mail="")
    r = adm.client.post("/admin/contas/confirmacao-lote/confirmar", data={"uid": ["ana", "bia", "caio"]})
    assert r.status_code == 200 and "Confirmação de dados em lote" in r.text
    assert 'action="/admin/contas/confirmacao-lote"' in r.text
    assert "2 contas receberão o pedido de confirmação dos dados" in r.text
    r = adm.client.post("/admin/contas/confirmacao-lote", data={"uid": ["ana", "bia", "caio"]})
    assert "Enviados: 2" in r.text and "sem e-mail: 1" in r.text
    assert sorted(e["para"] for e in adm.correio.enviados) == ["ana@exemplo.org", "bia@exemplo.org"]
    assert all("/confirmar-dados/" in e["texto"] for e in adm.correio.enviados)
    assert auditoria(adm.banco)[0]["acao"] == "confirmacao_lote"


def test_lote_de_confirmacao_respeita_limite(adm):
    for i in range(201):
        _conta(adm, uid=f"u{i:03d}", mail=f"u{i}@exemplo.org")
    r = adm.client.post("/admin/contas/confirmacao-lote/confirmar", data={"todos_do_filtro": "sim"})
    assert r.status_code == 400 and "o limite é 200" in r.text


def test_formulario_do_lote_tem_botao_de_confirmacao(adm):
    _conta(adm)
    html = adm.client.get("/admin/contas").text
    dica = "Pedir confirmação dos dados às selecionadas"
    assert f'formaction="/admin/contas/confirmacao-lote/confirmar" class="icone" title="{dica}"' in html


def _link_de_confirmacao(amb, uid="mariasouza"):
    tok = tokens.emitir(amb.banco, tokens.CONFIRMAR_DADOS, uid, 24, amb.relogio())
    return f"/confirmar-dados/{tok}"


def test_tela_mostra_dados_do_ldap(amb):
    _conta(amb)
    html = amb.client.get(_link_de_confirmacao(amb)).text
    assert "Confira seus dados" in html and "Maria Souza" in html and "529.982.247-25" in html
    assert "maria@exemplo.org" in html and "Aviso de privacidade" in html
    assert "Meus dados estão corretos</button>" in html and "disabled>Meus" not in html and "/corrigir" in html


def test_link_invalido(amb):
    assert amb.client.get("/confirmar-dados/xyz").status_code == 410


def test_conta_sumiu_do_ldap(amb):
    link = _link_de_confirmacao(amb, uid="naoexiste")
    assert amb.client.get(link).status_code == 410


def test_dados_corretos_vai_para_definir_senha(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    r = amb.client.post(link, data={"consentimento": "sim"})
    assert r.status_code == 302 and "/definir-senha/" in r.headers["Location"]
    assert amb.client.get(r.headers["Location"]).status_code == 200
    assert amb.client.get(link).status_code == 410  # uso único
    reg = auditoria(amb.banco)[0]
    assert reg["acao"] == "dados_confirmados" and reg["alvo"] == "mariasouza" and "aviso" in reg["detalhe"]


def test_dados_corretos_exige_consentimento(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    r = amb.client.post(link, data={})
    assert r.status_code == 400 and "aviso de privacidade" in r.text
    assert amb.client.get(link).status_code == 200  # link segue válido


def test_sem_cpf_nao_pode_confirmar(amb):
    _conta(amb, cpf="")
    link = _link_de_confirmacao(amb)
    html = amb.client.get(link).text
    assert "não informado" in html and "disabled>Meus dados estão corretos" in html
    assert amb.client.post(link, data={"consentimento": "sim"}).status_code == 400


def test_dados_faltando_mostra_card_com_botao_de_correcao(amb):
    _conta(amb, telefone="")
    link = _link_de_confirmacao(amb)
    html = amb.client.get(link).text
    card = html.split('<div class="card-faltam">', 1)[1].split("</div>", 1)[0]
    assert "Faltam dados no seu cadastro" in card
    assert f'<a class="botao" href="{link}/corrigir">Completar meus dados</a>' in card
    assert html.count(f'href="{link}/corrigir"') == 1


def test_dados_completos_sem_card_de_faltam(amb):
    _conta(amb)
    assert '<div class="card-faltam">' not in amb.client.get(_link_de_confirmacao(amb)).text


def test_segundo_post_apos_consumir_o_link_da_410(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    assert amb.client.post(link, data={"consentimento": "sim"}).status_code == 302
    assert amb.client.post(link, data={"consentimento": "sim"}).status_code == 410


def test_falha_no_ldap_da_503(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    amb.dir.falhar = True
    assert amb.client.get(link).status_code == 503


def _form(**over):
    base = {"nome": "Maria da Silva Souza", "cpf": "529.982.247-25", "email": "maria@exemplo.org",
            "telefone": "(11) 91234-5678", "justificativa": "", "consentimento": "sim"}
    base.update(over)
    return base


def test_corrigir_mostra_formulario_preenchido(amb):
    _conta(amb)
    html = amb.client.get(_link_de_confirmacao(amb) + "/corrigir").text
    assert 'value="Maria Souza"' in html and 'value="529.982.247-25"' in html and 'value="maria@exemplo.org"' in html
    assert "No cadastro ficam o primeiro nome e o último sobrenome." in html


def test_corrigir_link_invalido(amb):
    assert amb.client.get("/confirmar-dados/xyz/corrigir").status_code == 410


def test_corrigir_sem_mudanca_vai_para_senha(amb):
    _conta(amb)
    r = amb.client.post(_link_de_confirmacao(amb) + "/corrigir", data=_form())
    assert r.status_code == 302 and "/definir-senha/" in r.headers["Location"]
    assert amb.banco.contar_por_status("") == {}


def test_corrigir_telefone_cria_alteracao_e_nao_muda_ldap(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    r = amb.client.post(link + "/corrigir", data=_form(telefone="(21) 99876-5432"))
    assert r.status_code == 200 and "Recebemos sua correção" in r.text
    sol = amb.banco.buscar("", "pendente", 1)[0]
    assert sol["origem"] == "alteracao" and sol["uid_sugerido"] == "mariasouza" and sol["telefone"] == "+5521998765432"
    assert amb.dir.contas["mariasouza"]["telefone"] == "+5511912345678"
    assert amb.correio.enviados[-1]["para"] == amb.cfg.admin_notify_email
    assert "correção de dados para revisar" in amb.correio.enviados[-1]["assunto"]
    assert amb.client.get(link).status_code == 410
    assert any(a["acao"] == "alteracao_solicitada" and "telefone" in a["detalhe"] for a in auditoria(amb.banco))


def test_corrigir_valida_campos_e_consentimento(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    assert amb.client.post(link + "/corrigir", data=_form(cpf="123")).status_code == 400
    r = amb.client.post(link + "/corrigir", data=_form(telefone="(21) 99876-5432", consentimento=""))
    assert r.status_code == 400 and "aviso de privacidade" in r.text
    assert amb.client.get(link).status_code == 200


def test_corrigir_ldap_nao_normalizado_sem_mudanca_vai_para_senha(amb):
    _conta(amb, telefone="11912345678", mail="Maria@Exemplo.org")
    r = amb.client.post(_link_de_confirmacao(amb) + "/corrigir", data=_form())
    assert r.status_code == 302 and "/definir-senha/" in r.headers["Location"]
    assert amb.banco.contar_por_status("") == {}


def test_corrigir_segundo_post_apos_alteracao_da_410(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb) + "/corrigir"
    assert amb.client.post(link, data=_form(telefone="(21) 99876-5432")).status_code == 200
    assert amb.client.post(link, data=_form(telefone="(21) 99876-5432")).status_code == 410


def test_corrigir_falha_no_ldap_da_503(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb) + "/corrigir"
    amb.dir.falhar = True
    assert amb.client.get(link).status_code == 503


def test_corrigir_cpf_vazio_no_ldap_cria_alteracao(amb):
    _conta(amb, cpf="")
    r = amb.client.post(_link_de_confirmacao(amb) + "/corrigir", data=_form())
    assert r.status_code == 200 and "Recebemos sua correção" in r.text
    sol = amb.banco.buscar("", "pendente", 1)[0]
    assert sol["origem"] == "alteracao" and sol["cpf"] == "52998224725"


def test_corrigir_email_exige_confirmacao_antes_do_admin(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    r = amb.client.post(link + "/corrigir", data=_form(email="maria.nova@exemplo.org"))
    assert r.status_code == 200 and "maria.nova@exemplo.org" in r.text and "só segue" in r.text
    assert amb.banco.buscar("", "pendente", 1) == []
    sol = amb.banco.buscar("", "aguardando_confirmacao", 1)[0]
    assert sol["origem"] == "alteracao" and sol["email"] == "maria.nova@exemplo.org"
    assert amb.correio.enviados[-1]["para"] == "maria.nova@exemplo.org"  # nada foi ao admin
    assert all(e["para"] != amb.cfg.admin_notify_email for e in amb.correio.enviados)
    caminho = amb.correio.caminho_do_link()
    assert caminho.startswith("/confirmar-email/")
    assert amb.client.post(caminho).status_code == 200
    assert amb.banco.obter(sol["id"])["status"] == "pendente"
    assert amb.correio.enviados[-1]["para"] == amb.cfg.admin_notify_email
    assert "correção de dados para revisar" in amb.correio.enviados[-1]["assunto"]


def test_corrigir_email_falha_no_envio_remove_alteracao(amb):
    _conta(amb)
    link = _link_de_confirmacao(amb)
    amb.correio.falhar = True
    r = amb.client.post(link + "/corrigir", data=_form(email="maria.nova@exemplo.org"))
    assert r.status_code == 503
    assert amb.banco.buscar("", "aguardando_confirmacao", 1) == []
    assert all(e["para"] != amb.cfg.admin_notify_email for e in amb.correio.enviados)
    assert not any(a["acao"] == "alteracao_solicitada" for a in auditoria(amb.banco))
    assert amb.client.get(link).status_code == 410
