import json
import os
import re
import urllib.request

import pytest
from ldap3 import NONE, Connection, Server
from ldap3.core.exceptions import LDAPException

from app import create_app
from app.correio import Correio
from app.diretorio import Diretorio
from tests.fakes import Relogio, template_teste
from tests.unit.test_publico import FORM

MAILPIT = os.environ.get("MAILPIT_URL", "")
USERS = "ou=Users,dc=exemplo,dc=org"


def _mailpit(metodo, caminho):
    req = urllib.request.Request(MAILPIT + caminho, method=metodo)
    with urllib.request.urlopen(req, timeout=10) as r:
        corpo = r.read()
    return json.loads(corpo) if metodo == "GET" else None


def _ultimo_link_para(destino):
    for m in _mailpit("GET", "/api/v1/messages")["messages"]:
        if any(t["Address"] == destino for t in m["To"]):
            texto = _mailpit("GET", f"/api/v1/message/{m['ID']}")["Text"]
            return re.search(r"https://cadastro\.teste([^\s>]+)", texto).group(1)
    pytest.fail(f"nenhum e-mail para {destino}")


def _bind_ok(url, uid, senha):
    try:
        Connection(Server(url, get_info=NONE), f"uid={uid},{USERS}", senha, auto_bind=True).unbind()
        return True
    except LDAPException:
        return False


@pytest.fixture
def cliente(ldap, tmp_path):
    if not MAILPIT:
        pytest.skip("MAILPIT_URL não definido: rode via compose.test.yml")
    _mailpit("DELETE", "/api/v1/messages")
    template_teste(tmp_path)
    app = create_app(ldap.cfg, diretorio=Diretorio(ldap.cfg), correio=Correio(ldap.cfg), relogio=Relogio(),
                     testing=True)
    return app.test_client()


def test_solicitar_aprovar_definir_senha(ldap, cliente):
    r = cliente.post("/cadastro", data=FORM)
    pacote = re.search(r'name="pacote" value="([^"]+)"', r.text).group(1)
    assert cliente.post("/confirmar", data={"pacote": pacote, "consentimento": "sim"}).status_code == 200
    assert cliente.post(_ultimo_link_para("maria@exemplo.org")).status_code == 200  # confirmação por POST
    assert _ultimo_link_para("admin@teste.local").startswith("/admin/solicitacao/")

    assert cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"}).status_code == 302
    sid = int(_ultimo_link_para("admin@teste.local").rsplit("/", 1)[1])
    r = cliente.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert r.status_code == 302

    link = _ultimo_link_para("maria@exemplo.org")
    assert link.startswith("/definir-senha/")
    r = cliente.post(link, data={"senha": "Maria#2026", "confirmacao": "Maria#2026"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    assert _bind_ok(ldap.url, "mariasouza", "Maria#2026")
    assert cliente.get(link).status_code == 410


def test_reset_conta_antiga(ldap, cliente):
    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    cliente.post("/admin/contas/antigo/reset")
    link = _ultimo_link_para("antigo@teste.local")
    cliente.post(link, data={"senha": "Renovada#1", "confirmacao": "Renovada#1"})
    assert _bind_ok(ldap.url, "antigo", "Renovada#1")


def test_convidar_aceitar_definir_senha(ldap, cliente):
    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    r = cliente.post("/admin/convidar", data={"nome": "Joana Pereira Lima", "cpf": "123.456.789-09",
                                              "email": "joana@exemplo.org", "telefone": "(11) 98765-4321",
                                              "organizacao": "CLIENTE-A", "uid": ""})
    assert r.status_code == 302
    cliente.post("/admin/sair")

    link = _ultimo_link_para("joana@exemplo.org")
    assert link.startswith("/convite/")
    r = cliente.get(link)
    assert r.status_code == 200 and 'value="123.456.789-09"' in r.text
    r = cliente.post(link, data={"nome": "Joana Pereira Lima", "cpf": "123.456.789-09",
                                 "email": "joana@exemplo.org", "telefone": "+55 (11) 98765-4321",
                                 "justificativa": "", "consentimento": "sim"})
    assert r.status_code == 302 and "/definir-senha/" in r.headers["Location"]
    ldap.con.search(USERS, "(uid=joanalima)", attributes=["ou", "mail", "description"])
    [conta] = ldap.con.entries
    assert str(conta.ou) == "CLIENTE-A" and str(conta.mail) == "joana@exemplo.org"
    assert str(conta.description) == "CPF: 12345678909"

    r = cliente.post(r.headers["Location"], data={"senha": "Joana#2026", "confirmacao": "Joana#2026"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    assert _bind_ok(ldap.url, "joanalima", "Joana#2026")
    assert cliente.get(link).status_code == 410


def test_reset_em_lote(ldap, cliente):
    # aceite 27 com LDAP e SMTP reais: 3 contas (comum sem e-mail) → 2 links, 1 pulada; cada link define a senha
    ldap.con.add(f"uid=nova,{USERS}", ["inetOrgPerson", "posixAccount", "shadowAccount"], {
        "uid": "nova", "cn": "Nova Pessoa", "sn": "Pessoa", "uidNumber": "10060", "gidNumber": "10000",
        "homeDirectory": "/home/nova", "mail": "nova@exemplo.org", "ou": "CLIENTE-A"})
    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    r = cliente.get("/admin/contas?cliente=CLIENTE-A")
    assert 'value="antigo"' in r.text and 'value="nova"' in r.text and 'value="comum"' not in r.text
    r = cliente.post("/admin/contas/reset-lote", data={"uid": ["antigo", "nova", "comum"]})
    assert r.status_code == 200 and "Enviados: 2" in r.text and "Pulados: 1" in r.text
    for uid, destino in (("antigo", "antigo@teste.local"), ("nova", "nova@exemplo.org")):
        link = _ultimo_link_para(destino)
        assert link.startswith("/definir-senha/")
        assert cliente.post(link, data={"senha": "Lote#2026x", "confirmacao": "Lote#2026x"}).status_code == 302
        assert _bind_ok(ldap.url, uid, "Lote#2026x")


def test_convite_por_email_preencher_aprovar_definir_senha(ldap, cliente):
    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    r = cliente.post("/admin/convidar-por-email", data={"acao": "enviar", "email": ["paula@exemplo.org"],
                                                        "organizacao": "CLIENTE-A"},
        follow_redirects=True)
    assert r.status_code == 200
    cliente.post("/admin/sair")

    link = _ultimo_link_para("paula@exemplo.org")
    assert link.startswith("/convite/")
    r = cliente.post(link, data={"nome": "Paula Ribeiro Dias", "cpf": "123.456.789-09",
                                 "telefone": "(11) 98765-4321", "justificativa": "", "consentimento": "sim"})
    assert r.status_code == 200 and "Recebemos sua solicitação" in r.text
    sid = int(_ultimo_link_para("admin@teste.local").rsplit("/", 1)[1])

    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    r = cliente.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "paulados"})
    assert r.status_code == 302
    ldap.con.search(USERS, "(uid=paulados)", attributes=["ou", "mail"])
    [conta] = ldap.con.entries
    assert str(conta.ou) == "CLIENTE-A" and str(conta.mail) == "paula@exemplo.org"

    senha = _ultimo_link_para("paula@exemplo.org")
    assert senha.startswith("/definir-senha/")
    r = cliente.post(senha, data={"senha": "Paula#2026", "confirmacao": "Paula#2026"})
    assert r.status_code == 302
    assert _bind_ok(ldap.url, "paulados", "Paula#2026")
    assert cliente.get(link).status_code == 410


def test_convite_por_email_cliente_novo_pre_preenchido_na_aprovacao(ldap, cliente):
    import re
    from html import unescape
    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    r = cliente.post("/admin/convidar-por-email", data={
        "acao": "enviar", "email": ["rita@exemplo.org"], "organizacao": "__nova__",
        "organizacao_nova": "CLIENTENOVO", "confirmar_nova": "sim"}, follow_redirects=True)
    assert r.status_code == 200
    cliente.post("/admin/sair")
    link = _ultimo_link_para("rita@exemplo.org")
    r = cliente.post(link, data={"nome": "Rita Souza Lima", "cpf": "529.982.247-25",
                                 "telefone": "(11) 98765-4321", "justificativa": "", "consentimento": "sim"})
    assert r.status_code == 200
    sid = int(_ultimo_link_para("admin@teste.local").rsplit("/", 1)[1])

    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    html = cliente.get(f"/admin/solicitacao/{sid}").text
    assert '<option value="__nova__" selected>' in html
    nova = re.search(r'name="organizacao_nova" value="([^"]*)"', html)
    r = cliente.post(f"/admin/solicitacao/{sid}/aprovar", data={
        "organizacao": "__nova__", "organizacao_nova": unescape(nova.group(1)), "confirmar_nova": "sim",
        "uid": "ritasouza"})
    assert r.status_code == 302
    ldap.con.search(USERS, "(uid=ritasouza)", attributes=["ou"])
    [conta] = ldap.con.entries
    assert str(conta.ou) == "CLIENTENOVO"


def test_trocar_senha_pela_home(ldap, cliente):
    assert cliente.post("/entrar", data={"uid": "antigo", "senha": "Antiga#123"}).status_code == 302
    r = cliente.post("/minha-conta/senha", data={"atual": "Antiga#123", "senha": "Trocada#2026",
                                                  "confirmacao": "Trocada#2026"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    assert _bind_ok(ldap.url, "antigo", "Trocada#2026")
    assert not _bind_ok(ldap.url, "antigo", "Antiga#123")


def test_admin_informa_email_confirma_e_define_senha(ldap, cliente):
    cliente.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    r = cliente.post("/admin/contas/comum/email", data={"email": "comum@exemplo.org"})
    assert r.status_code == 302
    ldap.con.search(USERS, "(uid=comum)", attributes=["mail"])
    assert not ldap.con.entries[0].mail.values  # só vale depois de confirmar
    link = _ultimo_link_para("comum@exemplo.org")
    assert link.startswith("/confirmar-email-conta/")
    r = cliente.post(link)
    assert r.status_code == 302 and r.headers["Location"].startswith("/definir-senha/")
    ldap.con.search(USERS, "(uid=comum)", attributes=["mail"])
    assert str(ldap.con.entries[0].mail) == "comum@exemplo.org"
    r = cliente.post(r.headers["Location"], data={"senha": "Comum#2026x", "confirmacao": "Comum#2026x"})
    assert r.status_code == 302
    assert _bind_ok(ldap.url, "comum", "Comum#2026x")
