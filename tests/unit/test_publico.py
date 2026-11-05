import re

from app import tokens

FORM = {"nome": "Maria da Silva Souza", "cpf": "529.982.247-25", "email": "Maria@Exemplo.org",
        "telefone": "(11) 91234-5678", "justificativa": "Equipe de regulação, indicada pela coordenação."}


def _pacote(html: str) -> str:
    return re.search(r'name="pacote" value="([^"]+)"', html).group(1)


def _solicitar(amb, form=FORM, consentir=True):
    r = amb.client.post("/cadastro", data=form)
    assert r.status_code == 200, r.text
    dados = {"pacote": _pacote(r.text)}
    if consentir:
        dados["consentimento"] = "sim"
    return amb.client.post("/confirmar", data=dados)


def test_formulario_get(amb):
    r = amb.client.get("/cadastro")
    assert r.status_code == 200 and 'name="justificativa"' in r.text and 'name="site"' in r.text


def test_erros_de_validacao(amb):
    r = amb.client.post("/cadastro", data={**FORM, "cpf": "123"})
    assert r.status_code == 400 and "CPF inválido" in r.text
    assert amb.banco.buscar("", "aguardando_confirmacao", 1) == []


def test_revisao_mostra_dados_e_aviso(amb):
    r = amb.client.post("/cadastro", data=FORM)
    assert "maria@exemplo.org" in r.text and "Aviso de privacidade" in r.text
    assert 'name="consentimento"' in r.text and "checked" not in r.text


def test_sem_consentimento_nao_grava(amb):
    r = _solicitar(amb, consentir=False)
    assert r.status_code == 400 and "aviso de privacidade" in r.text
    assert amb.banco.buscar("", "aguardando_confirmacao", 1) == [] and amb.correio.enviados == []


def test_pacote_adulterado(amb):
    r = amb.client.post("/confirmar", data={"pacote": "x", "consentimento": "sim"})
    assert r.status_code == 400


def test_solicitacao_grava_consentimento_e_envia_confirmacao(amb):
    r = _solicitar(amb)
    assert r.status_code == 200 and "verifique" in r.text.lower()
    [sol] = amb.banco.buscar("", "aguardando_confirmacao", 1)
    assert sol["uid_sugerido"] == "mariasouza" and sol["telefone"] == "+5511912345678"
    c = amb.banco.consentimento(sol["id"])
    assert c["versao_aviso"] == amb.app.extensions["signup"].tema.privacidade_versao
    [email] = amb.correio.enviados
    assert email["para"] == "maria@exemplo.org"
    assert amb.correio.caminho_do_link().startswith("/confirmar-email/")


def test_honeypot_finge_sucesso(amb):
    r = amb.client.post("/cadastro", data={**FORM, "site": "spam"})
    assert r.status_code == 200 and "verifique" in r.text.lower()
    assert amb.correio.enviados == []


def test_rate_limit_formulario(amb):
    for _ in range(amb.cfg.rate_limit_form[0]):
        amb.client.post("/cadastro", data=FORM)
    assert amb.client.post("/cadastro", data=FORM).status_code == 429


def test_smtp_fora_nao_grava(amb):
    amb.correio.falhar = True
    r = _solicitar(amb)
    assert r.status_code == 503
    assert amb.banco.buscar("", "aguardando_confirmacao", 1) == []


def test_confirmar_email_vira_pendente_e_avisa_admin(amb):
    _solicitar(amb)
    r = amb.client.post(amb.correio.caminho_do_link())
    assert r.status_code == 200
    [sol] = amb.banco.buscar("", "pendente", 1)
    assert amb.banco.consentimento(sol["id"])["email_confirmado_em"] is not None
    aviso = amb.correio.enviados[-1]
    assert aviso["para"] == "admin@teste.local" and f"/admin/solicitacao/{sol['id']}" in aviso["texto"]


def test_link_de_confirmacao_expira(amb):
    _solicitar(amb)
    caminho = amb.correio.caminho_do_link()
    amb.relogio.avancar(hours=25)
    assert amb.client.post(caminho).status_code == 410
    assert amb.client.get(caminho).status_code == 410


def _token_senha(amb, uid="mariasouza"):
    amb.dir.contas[uid] = dict(uid=uid, cn="Maria Souza", mail="maria@exemplo.org", ou="CLIENTE-A",
                              cpf="52998224725", telefone="+5511912345678", senha=None)
    return tokens.emitir(amb.banco, tokens.DEFINIR_SENHA, uid, 24, amb.relogio())


def test_definir_senha_ok(amb):
    t = _token_senha(amb)
    assert amb.client.get(f"/definir-senha/{t}").status_code == 200
    r = amb.client.post(f"/definir-senha/{t}", data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    home = amb.client.get("/minha-conta").text
    assert "Senha definida." in home and "mariasouza" in home
    assert amb.dir.contas["mariasouza"]["senha"] == "Nova#Senha1"
    assert amb.client.get(f"/definir-senha/{t}").status_code == 410


def test_definir_senha_politica_e_confirmacao(amb):
    t = _token_senha(amb)
    r = amb.client.post(f"/definir-senha/{t}", data={"senha": "fraca", "confirmacao": "outra"})
    assert r.status_code == 400 and "maiúscula" in r.text and "iguais" in r.text
    assert amb.dir.contas["mariasouza"]["senha"] is None


def test_definir_senha_ldap_fora_mantem_token(amb):
    t = _token_senha(amb)
    amb.dir.falhar = True
    r = amb.client.post(f"/definir-senha/{t}", data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    assert r.status_code == 503
    amb.dir.falhar = False
    assert amb.client.get(f"/definir-senha/{t}").status_code == 200


def test_definir_senha_token_invalido(amb):
    assert amb.client.get("/definir-senha/nada").status_code == 410
    r = amb.client.post("/definir-senha/nada", data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    assert r.status_code == 410


def test_replay_do_pacote_respeita_limite_do_formulario(amb):
    r = amb.client.post("/cadastro", data=FORM)
    dados = {"pacote": _pacote(r.text), "consentimento": "sim"}
    limite = amb.cfg.rate_limit_form[0]
    codigos = [amb.client.post("/confirmar", data=dados).status_code for _ in range(limite + 5)]
    assert 429 in codigos
    assert len(amb.correio.enviados) <= limite - 1  # o POST / já gastou 1


def test_falha_de_smtp_nao_expira_solicitacao_anterior(amb):
    _solicitar(amb)
    amb.client.post(amb.correio.caminho_do_link())
    [anterior] = amb.banco.buscar("", "pendente", 1)
    amb.correio.falhar = True
    assert _solicitar(amb).status_code == 503
    assert amb.banco.obter(anterior["id"])["status"] == "pendente"


def test_get_do_link_de_confirmacao_nao_confirma(amb):
    _solicitar(amb)
    caminho = amb.correio.caminho_do_link()
    r = amb.client.get(caminho)
    assert r.status_code == 200 and "Confirmar e-mail" in r.text
    assert amb.banco.buscar("", "pendente", 1) == [] and len(amb.banco.buscar("", "aguardando_confirmacao", 1)) == 1
    assert amb.client.post(caminho).status_code == 200
    assert len(amb.banco.buscar("", "pendente", 1)) == 1
    assert amb.client.post(caminho).status_code == 410


def test_confirmacao_de_email_token_invalido(amb):
    assert amb.client.get("/confirmar-email/nada").status_code == 410
    assert amb.client.post("/confirmar-email/nada").status_code == 410


def test_pagina_do_aviso_de_privacidade_e_link_no_formulario(amb):
    r = amb.client.get("/privacidade")
    assert r.status_code == 200 and "Aviso de privacidade" in r.text
    assert 'href="/privacidade"' in amb.client.get("/cadastro").text


def test_definir_senha_preserva_sessao_admin(amb):
    from tests.unit.test_admin import _login as _login_admin  # import tardio: test_admin importa este módulo
    assert _login_admin(amb).status_code == 302
    t = _token_senha(amb)
    r = amb.client.post(f"/definir-senha/{t}", data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    assert r.status_code == 302
    assert amb.client.get("/admin/").status_code == 200
    assert "mariasouza" in amb.client.get("/minha-conta").text


def test_definir_senha_renova_csrf(amb):
    t = _token_senha(amb)
    with amb.client.session_transaction() as sess:
        sess["csrf_token"] = "velho"
    amb.client.post(f"/definir-senha/{t}", data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    with amb.client.session_transaction() as sess:
        assert sess.get("csrf_token") != "velho"


def test_inicio_tem_boas_vindas_e_botao_para_cadastro(amb):
    html = amb.client.get("/").text
    assert "Bem-vindo(a)" in html
    assert '<a class="botao" href="/cadastro">Solicitar acesso</a>' in html
    assert 'href="/entrar"' in html


def test_cadastro_em_nova_url(amb):
    assert 'name="cpf"' in amb.client.get("/cadastro").text
    assert amb.client.post("/").status_code == 405
