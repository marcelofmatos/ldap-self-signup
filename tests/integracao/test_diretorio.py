import dataclasses

from ldap3 import MODIFY_ADD, NONE, Connection, Server
from ldap3.core.exceptions import LDAPException

import pytest

from app.diretorio import Diretorio, ErroDiretorio

USERS = "ou=Users,dc=exemplo,dc=org"


def _entrada(con, uid):
    con.search(USERS, f"(uid={uid})", attributes=["*"])
    return con.entries[0].entry_attributes_as_dict


def _membros(con):
    con.search("cn=Usuario,ou=Groups,dc=exemplo,dc=org", "(objectClass=*)", attributes=["memberUid"])
    return set(con.entries[0].entry_attributes_as_dict.get("memberUid", []))


def _bind_ok(url, dn, senha):
    try:
        Connection(Server(url, get_info=NONE), dn, senha, auto_bind=True).unbind()
        return True
    except LDAPException:
        return False


def test_criar_conta_no_padrao(ldap):
    d = Diretorio(ldap.cfg)
    numero = d.criar_conta(uid="mariasouza", nome="Maria da Silva Souza", cpf="52998224725",
                           mail="maria@teste.local", telefone="+5511912345678", org="CLIENTE-A")
    assert numero == 10052
    e = _entrada(ldap.con, "mariasouza")
    assert e["cn"] == ["Maria Souza"] and e["ou"] == ["CLIENTE-A"] and e["o"] == ["CLIENTE-A"]
    assert e["description"] == ["CPF: 52998224725"] and e["mail"] == ["maria@teste.local"]
    assert e["telephoneNumber"] == ["+5511912345678"] and e["loginShell"] == ["/bin/bash"]
    assert "mariasouza" in _membros(ldap.con)


def test_criar_conta_com_memberuid_ja_presente(ldap):
    ldap.con.modify("cn=Usuario,ou=Groups,dc=exemplo,dc=org",
                    {"memberUid": [(MODIFY_ADD, ["mariasouza"])]})
    Diretorio(ldap.cfg).criar_conta(uid="mariasouza", nome="Maria da Silva Souza", cpf="52998224725",
                                    mail="maria@teste.local", telefone="+5511912345678", org="CLIENTE-A")
    assert _entrada(ldap.con, "mariasouza")["uid"] == ["mariasouza"]


def test_criar_conta_desfaz_se_grupo_falha(ldap):
    cfg = dataclasses.replace(
        ldap.cfg, ldap_default_group_dn="cn=NaoExiste,ou=Groups,dc=exemplo,dc=org")
    with pytest.raises(ErroDiretorio):
        Diretorio(cfg).criar_conta(uid="mariasouza", nome="Maria da Silva Souza", cpf="52998224725",
                                   mail="maria@teste.local", telefone="+5511912345678", org="CLIENTE-A")
    ldap.con.search(USERS, "(uid=mariasouza)", attributes=["uid"])
    assert ldap.con.entries == []


def test_criar_conta_uid_existente(ldap):
    with pytest.raises(ErroDiretorio):
        Diretorio(ldap.cfg).criar_conta(uid="antigo", nome="Outro Antigo", cpf="52998224725",
                                        mail="x@teste.local", telefone="+5511912345678", org="CLIENTE-A")


def test_definir_senha_e_bind(ldap):
    Diretorio(ldap.cfg).definir_senha("antigo", "Nova#Senha1")
    assert _bind_ok(ldap.url, f"uid=antigo,{USERS}", "Nova#Senha1")
    assert not _bind_ok(ldap.url, f"uid=antigo,{USERS}", "Antiga#123")


def test_autenticar_admin(ldap):
    d = Diretorio(ldap.cfg)
    assert d.autenticar_admin("chefe", "Chefe#123") is True
    assert d.autenticar_admin("chefe", "errada") is False
    assert d.autenticar_admin("antigo", "Antiga#123") is False  # fora do grupo
    assert d.autenticar_admin("ninguem", "x") is False
    assert d.autenticar_admin("chefe", "") is False


def test_conflitos_organizacoes_busca(ldap):
    d = Diretorio(ldap.cfg)
    # conflitos devolve, por critério, os uids das contas encontradas
    assert d.conflitos("antigo", "11144477735", "antigo@teste.local") == {
        "uid": ["antigo"], "cpf": ["antigo"], "mail": ["antigo"]}
    assert d.conflitos("novo", "52998224725", "novo@teste.local") == {"uid": [], "cpf": [], "mail": []}
    assert d.organizacoes() == ["CLIENTE-A"]
    assert d.obter_conta("antigo") == {"uid": "antigo", "cn": "Antigo Usuario",
                                       "mail": "antigo@teste.local", "ou": "CLIENTE-A",
                                       "cpf": "11144477735", "telefone": ""}
    assert d.obter_conta("ninguem") is None


def test_autenticar_admin_so_por_lista(ldap):
    # aceite 11: sem grupo, só a lista vale
    d = Diretorio(dataclasses.replace(ldap.cfg, admin_group_dn="", admin_uids=("antigo",)))
    assert d.autenticar_admin("antigo", "Antiga#123") is True
    assert d.autenticar_admin("antigo", "errada") is False
    assert d.autenticar_admin("chefe", "Chefe#123") is False
    assert d.autenticar_admin("comum", "Comum#123") is False


def test_autenticar_admin_lista_que_nao_existe_no_ldap(ldap):
    d = Diretorio(dataclasses.replace(ldap.cfg, admin_group_dn="", admin_uids=("ninguem",)))
    assert d.autenticar_admin("ninguem", "x") is False


def test_autenticar_admin_lista_e_grupo(ldap):
    # aceite 12: lista OU grupo; quem não está em nenhum não entra
    d = Diretorio(dataclasses.replace(ldap.cfg, admin_uids=("antigo",)))
    assert d.autenticar_admin("chefe", "Chefe#123") is True
    assert d.autenticar_admin("antigo", "Antiga#123") is True
    assert d.autenticar_admin("comum", "Comum#123") is False


def test_autenticar_admin_grupo_inexistente_vira_erro(ldap):
    cfg = dataclasses.replace(ldap.cfg, admin_uids=("antigo",),
                              admin_group_dn="cn=NaoExiste,ou=Groups,dc=exemplo,dc=org")
    with pytest.raises(ErroDiretorio):
        Diretorio(cfg).autenticar_admin("chefe", "Chefe#123")


def test_autenticar_admin_so_lista_bind_de_servico_falho_vira_erro(ldap):
    cfg = dataclasses.replace(ldap.cfg, admin_group_dn="", admin_uids=("antigo",), ldap_bind_pw="errada")
    with pytest.raises(ErroDiretorio):
        Diretorio(cfg).autenticar_admin("antigo", "Antiga#123")


def test_autenticar_admin_bind_de_servico_falho_vira_erro(ldap):
    d = Diretorio(dataclasses.replace(ldap.cfg, ldap_bind_pw="errada"))
    with pytest.raises(ErroDiretorio):
        d.autenticar_admin("chefe", "Chefe#123")


def test_listar_contas_com_grupos(ldap):
    contas = Diretorio(ldap.cfg).listar_contas()
    assert [c["uid"] for c in contas] == ["antigo", "chefe", "comum"]
    antigo, chefe, comum = contas
    assert antigo == {"uid": "antigo", "cn": "Antigo Usuario", "mail": "antigo@teste.local", "ou": "CLIENTE-A",
                      "cpf": "11144477735", "grupos": ["Usuario"]}
    assert chefe["grupos"] == ["Cadastro Admins", "Usuario"] and chefe["mail"] == "" and chefe["ou"] == ""
    assert comum["cpf"] == "" and comum["grupos"] == ["Usuario"]


def test_listar_contas_bind_falho_vira_erro(ldap):
    with pytest.raises(ErroDiretorio):
        Diretorio(dataclasses.replace(ldap.cfg, ldap_bind_pw="errada")).listar_contas()


def test_obter_conta_traz_cpf_e_telefone(ldap):
    d = Diretorio(ldap.cfg)
    d.criar_conta(uid="mariasouza", nome="Maria da Silva Souza", cpf="52998224725",
                  mail="maria@teste.local", telefone="+5511912345678", org="CLIENTE-A")
    conta = d.obter_conta("mariasouza")
    assert conta == {"uid": "mariasouza", "cn": "Maria Souza", "mail": "maria@teste.local", "ou": "CLIENTE-A",
                     "cpf": "52998224725", "telefone": "+5511912345678"}


def test_atualizar_dados_preserva_uid_ou_e_outras_descricoes(ldap):
    d = Diretorio(ldap.cfg)
    d.criar_conta(uid="mariasouza", nome="Maria da Silva Souza", cpf="52998224725",
                  mail="maria@teste.local", telefone="+5511912345678", org="CLIENTE-A")
    ldap.con.modify(f"uid=mariasouza,{USERS}", {"description": [(MODIFY_ADD, ["Equipe X"])]})
    d.atualizar_dados("mariasouza", nome="Maria Clara Lima", cpf="11144477735", mail="clara@teste.local",
                      telefone="+5521998765432")
    e = _entrada(ldap.con, "mariasouza")
    assert e["cn"] == ["Maria Lima"] and e["sn"] == ["Lima"] and e["givenName"] == ["Maria"]
    assert e["gecos"] == ["Maria Lima"] and e["mail"] == ["clara@teste.local"]
    assert e["telephoneNumber"] == ["+5521998765432"]
    assert sorted(e["description"]) == ["CPF: 11144477735", "Equipe X"]
    assert e["uid"] == ["mariasouza"] and e["ou"] == ["CLIENTE-A"]


def test_atualizar_dados_conta_inexistente(ldap):
    with pytest.raises(ErroDiretorio):
        Diretorio(ldap.cfg).atualizar_dados("naoexiste", nome="Ana Lima", cpf="11144477735",
                                            mail="a@teste.local", telefone="+5521998765432")


def test_autenticar_qualquer_conta(ldap):
    d = Diretorio(ldap.cfg)
    assert d.autenticar("antigo", "Antiga#123") is True
    assert d.autenticar("antigo", "errada") is False
    assert d.autenticar("ninguem", "x") is False
    assert d.autenticar("antigo", "") is False
    assert d.autenticar("", "Antiga#123") is False


def test_grupos_de(ldap):
    d = Diretorio(ldap.cfg)
    assert d.grupos_de("chefe") == ["Cadastro Admins", "Usuario"]
    assert d.grupos_de("antigo") == ["Usuario"]
    assert d.grupos_de("ninguem") == []


def test_autenticar_bind_falho_vira_erro(ldap):
    with pytest.raises(ErroDiretorio):
        Diretorio(dataclasses.replace(ldap.cfg, ldap_bind_pw="errada")).autenticar("antigo", "Antiga#123")


def test_contas_por_email(ldap):
    d = Diretorio(ldap.cfg)
    for mail in ("antigo@teste.local", "ANTIGO@teste.local"):
        achadas = d.contas_por_email(mail)
        assert [(c["uid"], c["cn"]) for c in achadas] == [("antigo", "Antigo Usuario")]
    assert d.contas_por_email("ninguem@teste.local") == []
    assert d.contas_por_email("*") == []


def test_definir_email_troca_so_o_mail(ldap):
    d = Diretorio(ldap.cfg)
    antes = _entrada(ldap.con, "antigo")
    d.definir_email("antigo", "novo@teste.local")
    depois = _entrada(ldap.con, "antigo")
    assert depois["mail"] == ["novo@teste.local"]
    assert {k: v for k, v in depois.items() if k != "mail"} == {k: v for k, v in antes.items() if k != "mail"}


def test_definir_email_conta_inexistente(ldap):
    with pytest.raises(ErroDiretorio):
        Diretorio(ldap.cfg).definir_email("naoexiste", "a@teste.local")
