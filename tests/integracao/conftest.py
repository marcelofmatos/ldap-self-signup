import os
import time
from types import SimpleNamespace

import pytest
from ldap3 import LEVEL, MODIFY_REPLACE, NONE, Connection, Server
from ldap3.core.exceptions import LDAPException

from app.contas import hash_ssha
from tests.fakes import config_teste

BASE = "dc=exemplo,dc=org"
USERS = f"ou=Users,{BASE}"
GROUPS = f"ou=Groups,{BASE}"


def _conectar(url, dn, pw):
    servidor = Server(url, get_info=NONE)
    for _ in range(30):
        try:
            return Connection(servidor, dn, pw, auto_bind=True)
        except LDAPException:
            time.sleep(1)
    pytest.fail("openldap de teste não respondeu em 30s")


def _semear(con):
    for dn, oc, attrs in [
        (USERS, ["organizationalUnit"], {"ou": "Users"}),
        (GROUPS, ["organizationalUnit"], {"ou": "Groups"}),
        (f"cn=Usuario,{GROUPS}", ["posixGroup"], {"cn": "Usuario", "gidNumber": "10000"}),
        (f"cn=Cadastro Admins,{GROUPS}", ["posixGroup"], {"cn": "Cadastro Admins", "gidNumber": "10099"}),
    ]:
        con.add(dn, oc, attrs)  # já existe → ignora
    con.search(USERS, "(objectClass=*)", LEVEL)
    for entrada in list(con.entries):
        con.delete(entrada.entry_dn)
    pessoa = ["inetOrgPerson", "posixAccount", "shadowAccount"]
    con.add(f"uid=chefe,{USERS}", pessoa, {
        "uid": "chefe", "cn": "Chefe Teste", "sn": "Teste", "uidNumber": "10050", "gidNumber": "10000",
        "homeDirectory": "/home/chefe", "userPassword": hash_ssha("Chefe#123")})
    con.add(f"uid=antigo,{USERS}", pessoa, {
        "uid": "antigo", "cn": "Antigo Usuario", "sn": "Usuario", "uidNumber": "10051", "gidNumber": "10000",
        "homeDirectory": "/home/antigo", "mail": "antigo@teste.local", "ou": "CLIENTE-A", "o": "CLIENTE-A",
        "description": "CPF: 11144477735", "userPassword": hash_ssha("Antiga#123")})
    con.add(f"uid=comum,{USERS}", pessoa, {
        "uid": "comum", "cn": "Comum Teste", "sn": "Teste", "uidNumber": "10049", "gidNumber": "10000",
        "homeDirectory": "/home/comum", "userPassword": hash_ssha("Comum#123")})
    con.modify(f"cn=Usuario,{GROUPS}", {"memberUid": [(MODIFY_REPLACE, ["chefe", "antigo", "comum"])]})
    con.modify(f"cn=Cadastro Admins,{GROUPS}", {"memberUid": [(MODIFY_REPLACE, ["chefe"])]})


@pytest.fixture
def ldap(tmp_path):
    """LDAP de teste recém-semeado: chefe (admin), antigo (CLIENTE-A, com mail) e comum (sem grupo de admin)."""
    url = os.environ.get("LDAP_TEST_URL")
    if not url:
        pytest.skip("LDAP_TEST_URL não definido: rode via compose.test.yml")
    dn, pw = os.environ["LDAP_TEST_ADMIN_DN"], os.environ["LDAP_TEST_ADMIN_PW"]
    con = _conectar(url, dn, pw)
    _semear(con)
    cfg = config_teste(tmp_path, ldap_url=url, ldap_bind_dn=dn, ldap_bind_pw=pw,
                       smtp_host=os.environ.get("MAILPIT_SMTP_HOST", "localhost"))
    yield SimpleNamespace(con=con, cfg=cfg, url=url)
    con.unbind()
