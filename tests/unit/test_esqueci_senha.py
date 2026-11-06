import logging
import re

from app import tokens
from tests.fakes import auditoria

MSG = "Se o e-mail estiver cadastrado, enviamos um link para definir uma nova senha."


def _conta(amb, uid="mariasouza", mail="maria@exemplo.org"):
    amb.dir.contas[uid] = dict(uid=uid, cn="Maria Souza", mail=mail, ou="CLIENTE-A", cpf="52998224725",
                               telefone="+5511912345678", senha="Antiga#123", grupos=[])


def test_tela(amb):
    html = amb.client.get("/esqueci-senha").text
    assert 'name="email"' in html


def test_email_cadastrado_recebe_link_e_define_senha(amb):
    _conta(amb)
    r = amb.client.post("/esqueci-senha", data={"email": " Maria@Exemplo.org "})
    assert r.status_code == 200 and MSG in r.text
    assert amb.correio.enviados[-1]["para"] == "maria@exemplo.org"
    assert "mariasouza" in amb.correio.enviados[-1]["texto"]
    caminho = amb.correio.caminho_do_link()
    assert caminho.startswith("/definir-senha/")
    r = amb.client.post(caminho, data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    assert r.status_code == 302 and amb.dir.contas["mariasouza"]["senha"] == "Nova#Senha1"
    a = auditoria(amb.banco)
    assert any(x["acao"] == "reset_senha" and x["ator"] == "publico" and x["alvo"] == "mariasouza"
               and x["detalhe"] == "esqueci_senha" for x in a)


def test_email_inexistente_mesma_mensagem_sem_envio(amb):
    _conta(amb)
    r = amb.client.post("/esqueci-senha", data={"email": "ninguem@exemplo.org"})
    assert r.status_code == 200 and MSG in r.text
    assert amb.correio.enviados == []


def test_falha_no_smtp_mesma_mensagem(amb):
    _conta(amb)
    amb.correio.falhar = True
    r = amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert r.status_code == 200 and MSG in r.text
    assert any(x["detalhe"] == "esqueci_senha · falha_envio" for x in auditoria(amb.banco))


def test_duas_contas_com_o_mesmo_email(amb):
    _conta(amb)
    _conta(amb, uid="maria2")
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert len(amb.correio.enviados) == 2


def test_email_invalido(amb):
    r = amb.client.post("/esqueci-senha", data={"email": "xx"})
    assert r.status_code == 400 and "E-mail inválido." in r.text


def test_ldap_fora(amb):
    amb.dir.falhar = True
    assert amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"}).status_code == 503


def test_pedido_publico_nao_invalida_link_do_admin(amb):
    _conta(amb)
    s = amb.app.extensions["signup"]
    do_admin = tokens.emitir(s.banco, tokens.DEFINIR_SENHA, "mariasouza", 24, s.agora())
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert amb.client.get(f"/definir-senha/{do_admin}").status_code == 200
    assert amb.client.get(amb.correio.caminho_do_link()).status_code == 200


def test_usar_um_link_invalida_os_outros_da_conta(amb):
    _conta(amb)
    s = amb.app.extensions["signup"]
    do_admin = tokens.emitir(s.banco, tokens.DEFINIR_SENHA, "mariasouza", 24, s.agora())
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    meu = amb.correio.caminho_do_link()
    r = amb.client.post(meu, data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    assert r.status_code == 302
    assert amb.client.get(f"/definir-senha/{do_admin}").status_code == 410


def test_intervalo_por_conta(amb):
    _conta(amb)
    for _ in range(2):
        r = amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
        assert r.status_code == 200 and MSG in r.text
    assert len(amb.correio.enviados) == 1
    assert any(x["detalhe"] == "esqueci_senha · ignorado (intervalo)" for x in auditoria(amb.banco))
    amb.relogio.avancar(minutes=16)
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert len(amb.correio.enviados) == 2


def test_falha_de_envio_tambem_conta_no_intervalo(amb):
    _conta(amb)
    amb.correio.falhar = True
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    amb.correio.falhar = False
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert amb.correio.enviados == []


def test_limite_por_ip(amb):
    codigos = [amb.client.post("/esqueci-senha", data={"email": "x@exemplo.org"}).status_code
               for _ in range(amb.cfg.rate_limit_form[0] + 1)]
    assert codigos[-1] == 429 and set(codigos[:-1]) == {200}


def test_links_do_tema_vao_no_contexto_do_email(amb):
    _conta(amb)
    tema = amb.app.extensions["signup"].tema
    tema.dados["links"] = {"Arquivos": "https://arq.exemplo.org"}
    ctxs = []
    original = tema.email
    tema.email = lambda modelo, **ctx: (ctxs.append(ctx), original(modelo, **ctx))[1]
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert ctxs[-1]["links"] == {"Arquivos": "https://arq.exemplo.org"}


def test_links_para_esqueci_senha(amb):
    assert 'href="/esqueci-senha"' in amb.client.get("/entrar").text
    assert 'href="/esqueci-senha"' in amb.client.get("/").text


def _corpo(r):
    return re.sub(r'name="csrf_token" value="[^"]*"', "", r.text)


def test_resposta_identica_para_existente_inexistente_e_intervalo(amb):
    _conta(amb)
    existente = amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    intervalo = amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    inexistente = amb.client.post("/esqueci-senha", data={"email": "ninguem@exemplo.org"})
    assert _corpo(existente) == _corpo(inexistente) == _corpo(intervalo)
    assert existente.status_code == inexistente.status_code == intervalo.status_code == 200


def test_excecao_em_segundo_plano_e_engolida_e_logada(amb, monkeypatch, caplog):
    _conta(amb)
    def quebra(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(amb.app.extensions["signup"].tema, "email", quebra)
    with caplog.at_level(logging.ERROR, logger="ldap-self-signup"):
        r = amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert r.status_code == 200 and MSG in r.text
    assert "falha ao processar esqueci-senha" in caplog.text


def test_email_traz_links_do_cliente(amb):
    _conta(amb)
    s = amb.app.extensions["signup"]
    s.tema.dados["links"] = {"Chat": "https://chat.x"}
    s.tema.por_cliente = {"cliente-a": ({"Painel A": "https://a.x"}, [])}
    contextos = []
    original = s.tema.email
    s.tema.email = lambda modelo, /, **ctx: (contextos.append(ctx), original(modelo, **ctx))[1]
    amb.client.post("/esqueci-senha", data={"email": "maria@exemplo.org"})
    assert contextos[-1]["links"] == {"Chat": "https://chat.x", "Painel A": "https://a.x"}
