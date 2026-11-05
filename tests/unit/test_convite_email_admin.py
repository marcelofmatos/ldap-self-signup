import re
from html import unescape

from app.web.admin import LIMITE_LOTE
from tests.unit.test_admin import _login

URL = "/admin/convidar-por-email"
CAIXA = "a@x.org, b@x.org\nxx\na@x.org existente@x.org"


def _admin(amb):
    amb.dir.contas["existente"] = dict(uid="existente", cn="E", mail="existente@x.org", ou="CLIENTE-A", cpf="9",
                                       telefone="", senha=None)
    _login(amb)


def _enviar(amb, emails, **extra):
    return amb.client.post(URL, data={"acao": "enviar", "email": emails, "organizacao": "CLIENTE-A", **extra},
                           follow_redirects=True)


def test_get_exige_admin(amb):
    assert amb.client.get(URL).status_code == 302


def test_get_mostra_caixa_e_cliente(amb):
    _admin(amb)
    r = amb.client.get(URL)
    assert r.status_code == 200 and 'name="emails"' in r.text and 'name="organizacao"' in r.text
    assert "CLIENTE-A" in r.text and "Convidar por e-mail" in r.text


def test_previa(amb):
    _admin(amb)
    r = amb.client.post(URL, data={"acao": "previa", "emails": CAIXA, "organizacao": "CLIENTE-A"})
    assert r.status_code == 200
    assert r.text.count('name="email"') == 2
    assert 'value="a@x.org"' in r.text and 'value="b@x.org"' in r.text
    assert r.text.count('value="a@x.org"') == 1 and "E-mail inválido." in r.text
    assert "Já tem conta (usuário existente)" in r.text


def test_previa_substitui_convite_em_aberto(amb):
    _admin(amb)
    sid = amb.banco.criar_convite_email("a@x.org", organizacao="CLIENTE-A", convidado_por="chefe", agora=amb.relogio())
    r = amb.client.post(URL, data={"acao": "previa", "emails": "a@x.org", "organizacao": "CLIENTE-A"})
    assert f"substitui o convite #{sid}" in r.text


def test_envio_cria_convites_e_envia(amb):
    _admin(amb)
    r = _enviar(amb, ["a@x.org", "b@x.org"])
    assert r.status_code == 200
    assert len(amb.correio.enviados) == 2
    for email in ("a@x.org", "b@x.org"):
        [sol] = amb.banco.buscar(email, "convidado", 1)
        assert (sol["origem"], sol["organizacao"], sol["convidado_por"]) == ("convite_email", "CLIENTE-A", "chefe")
    assert "Enviados: 2" in r.text


def test_envio_revalida_no_servidor(amb):
    _admin(amb)
    r = _enviar(amb, ["a@x.org", "xx", "existente@x.org"])
    assert r.status_code == 200 and len(amb.correio.enviados) == 1
    resultado = r.text.split("<tbody>")[1]
    assert "xx</td>" in resultado and "pulado: E-mail inválido." in resultado
    assert "existente@x.org</td>" in resultado and "pulado: Já tem conta (usuário existente)" in resultado


def test_cliente_novo_exige_confirmacao(amb):
    _admin(amb)
    r = amb.client.post(URL, data={"acao": "enviar", "email": ["a@x.org"], "organizacao": "__nova__",
                                   "organizacao_nova": "NOVO"})
    assert r.status_code == 400 and "Confirme a criação do cliente novo." in r.text
    assert amb.correio.enviados == []
    r = amb.client.post(URL, data={"acao": "enviar", "email": ["a@x.org"], "organizacao": "__nova__",
                                   "organizacao_nova": "NOVO", "confirmar_nova": "sim"},
                         follow_redirects=True)
    assert r.status_code == 200
    [sol] = amb.banco.buscar("a@x.org", "convidado", 1)
    assert sol["organizacao"] == "NOVO"


def test_limite_do_lote(amb):
    _admin(amb)
    r = _enviar(amb, [f"u{i}@x.org" for i in range(LIMITE_LOTE + 1)])
    assert r.status_code == 400 and "dividir" in r.text
    assert amb.correio.enviados == []


def test_ldap_fora_503(amb):
    _admin(amb)
    amb.dir.falhar = True
    assert amb.client.get(URL).status_code == 503


def test_smtp_falhando_conta_como_falha(amb):
    _admin(amb)
    amb.correio.falhar = True
    r = _enviar(amb, ["a@x.org"])
    assert r.status_code == 200 and "Falhas de envio: 1" in r.text
    [sol] = amb.banco.buscar("a@x.org", "convidado", 1)
    assert sol["link_enviado"] == 0


def test_lista_e_detalhe_mostram_o_email(amb):
    _admin(amb)
    _enviar(amb, ["a@x.org"])
    [sol] = amb.banco.buscar("a@x.org", "convidado", 1)
    lista = amb.client.get("/admin/?status=convidado")
    assert "<strong title=\"a@x.org\">a@x.org</strong>" in lista.text
    det = amb.client.get(f"/admin/solicitacao/{sol['id']}")
    assert "Convite por e-mail (por chefe)" in det.text


def test_reenviar_usa_modelo_convite_email(amb):
    _admin(amb)
    _enviar(amb, ["a@x.org"])
    [sol] = amb.banco.buscar("a@x.org", "convidado", 1)
    amb.client.post(f"/admin/solicitacao/{sol['id']}/reenviar-convite")
    assert len(amb.correio.enviados) == 2 and "Olá!" in amb.correio.enviados[1]["texto"]


def test_menu_tem_link(amb):
    _admin(amb)
    assert "Convidar por e-mail" in amb.client.get("/admin/").text


def test_cliente_novo_sobrevive_da_previa_ao_envio(amb):
    import re
    from html import unescape
    _admin(amb)
    r = amb.client.post(URL, data={"acao": "previa", "emails": "a@x.org", "organizacao": "__nova__",
                                   "organizacao_nova": "NOVO", "confirmar_nova": "sim"})
    html = r.text
    org = re.search(r'<option value="([^"]*)" selected', html)
    nova = re.search(r'name="organizacao_nova" value="([^"]*)"', html)
    conf = re.search(r'<input type="checkbox" name="confirmar_nova" value="sim" checked>', html)
    assert org and org.group(1) == "__nova__" and nova and conf
    r = amb.client.post(URL, data={"acao": "enviar", "email": ["a@x.org"], "organizacao": org.group(1),
                                   "organizacao_nova": unescape(nova.group(1)), "confirmar_nova": "sim"},
                         follow_redirects=True)
    assert r.status_code == 200 and "Cliente: NOVO." in r.text


def test_sem_enviaveis_nao_mostra_botao_de_envio(amb):
    _admin(amb)
    r = amb.client.post(URL, data={"acao": "previa", "emails": "xx", "organizacao": "CLIENTE-A"})
    assert r.status_code == 200 and "Enviar convites" not in r.text


def test_envio_redireciona_e_recarregar_nao_reenvia(amb):
    _admin(amb)
    r = amb.client.post(URL, data={"acao": "enviar", "email": ["a@x.org"], "organizacao": "CLIENTE-A"})
    assert r.status_code == 302 and "/convidar-por-email/resultado/" in r.headers["Location"]
    assert len(amb.correio.enviados) == 1
    for _ in range(2):
        r2 = amb.client.get(r.headers["Location"])
        assert r2.status_code == 200 and "Enviados: 1" in r2.text and "Cliente: CLIENTE-A." in r2.text
    assert len(amb.correio.enviados) == 1
    assert len(amb.banco.buscar("a@x.org", "convidado", 1)) == 1


def test_resultado_inexistente_ou_de_outro_admin_410(amb):
    _admin(amb)
    assert amb.client.get("/admin/convidar-por-email/resultado/999").status_code == 410


def test_400_no_enviar_preserva_a_lista_colada(amb):
    _admin(amb)
    r = amb.client.post(URL, data={"acao": "enviar", "email": ["a@x.org"], "organizacao": "__nova__",
                                   "organizacao_nova": "NOVO", "emails": "a@x.org, b@x.org"})
    assert r.status_code == 400
    assert re.search(r'<textarea[^>]*name="emails"[^>]*>a@x.org, b@x.org</textarea>', r.text)


def test_previa_carrega_a_lista_original_para_voltar(amb):
    _admin(amb)
    r = amb.client.post(URL, data={"acao": "previa", "emails": CAIXA, "organizacao": "CLIENTE-A"})
    m = re.search(r'<input type="hidden" name="emails" value="([^"]*)"', r.text)
    assert m and unescape(m.group(1)) == CAIXA
    assert 'value="voltar"' in r.text  # "Voltar" é um botão que reenvia a lista
    r = amb.client.post(URL, data={"acao": "voltar", "emails": unescape(m.group(1)), "organizacao": "CLIENTE-A"})
    assert r.status_code == 200 and "</textarea>" in r.text and "xx" in r.text.split("<textarea")[1]
