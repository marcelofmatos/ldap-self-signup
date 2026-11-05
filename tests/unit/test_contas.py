from datetime import date

import pytest

from app import contas
from app.contas import DadosInvalidos
from tests.fakes import confere_ssha

CPF_OK = "52998224725"  # CPF de exemplo válido (não é de pessoa real do projeto)


def test_validar_cpf_aceita_formatado_e_retorna_digitos():
    assert contas.validar_cpf("529.982.247-25") == CPF_OK


@pytest.mark.parametrize("cpf", ["529.982.247-24", "111.111.111-11", "123", ""])
def test_validar_cpf_rejeita_invalido(cpf):
    with pytest.raises(DadosInvalidos):
        contas.validar_cpf(cpf)


def test_validar_nome_normaliza_espacos():
    assert contas.validar_nome("  Maria   da Silva  Souza ") == "Maria da Silva Souza"


@pytest.mark.parametrize("nome", ["Maria", "Maria 123", "<b>x</b> y", "A b", "Ææ Øø", "-- --", "'' ''"])
def test_validar_nome_rejeita(nome):
    with pytest.raises(DadosInvalidos):
        contas.validar_nome(nome)


def test_validar_email_minusculo():
    assert contas.validar_email(" Maria.Souza@Exemplo.ORG ") == "maria.souza@exemplo.org"


def test_validar_email_rejeita():
    with pytest.raises(DadosInvalidos):
        contas.validar_email("maria@")


@pytest.mark.parametrize("entrada,esperado", [
    ("(11) 91234-5678", "+5511912345678"),
    ("11 3123-4567", "+551131234567"),
    ("+55 11 91234-5678", "+5511912345678"),
    ("5511912345678", "+5511912345678"),
    ("+351 912 345 678", "+351912345678"),
])
def test_normalizar_telefone(entrada, esperado):
    assert contas.normalizar_telefone(entrada) == esperado


def test_normalizar_telefone_rejeita():
    with pytest.raises(DadosInvalidos):
        contas.normalizar_telefone("1234")


def test_validar_formulario_junta_erros_por_campo():
    dados, erros = contas.validar_formulario({
        "nome": "Maria da Silva Souza", "cpf": "000", "email": "maria@exemplo.org",
        "telefone": "(11) 91234-5678", "justificativa": "curta",
    })
    assert set(erros) == {"cpf", "justificativa"}
    assert dados["nome"] == "Maria da Silva Souza"


def test_validar_formulario_ok():
    dados, erros = contas.validar_formulario({
        "nome": "Maria da Silva Souza", "cpf": "529.982.247-25", "email": "Maria@Exemplo.org",
        "telefone": "(11) 91234-5678", "justificativa": "Equipe de regulação, indicada pela coordenação.",
    })
    assert erros == {}
    assert dados == {
        "nome": "Maria da Silva Souza", "cpf": CPF_OK, "email": "maria@exemplo.org",
        "telefone": "+5511912345678", "justificativa": "Equipe de regulação, indicada pela coordenação.",
    }


def test_derivar_nomes_primeiro_e_ultimo_sem_acento():
    assert contas.derivar_nomes("Patrícia Alves da Silva Dias") == {
        "uid": "patriciadias", "given_name": "Patricia", "sn": "Dias", "cn": "Patricia Dias",
    }


def test_derivar_nomes_apostrofo_e_hifen():
    assert contas.derivar_nomes("Ana D'Ávila Costa-Lima")["uid"] == "analima"


@pytest.mark.parametrize("uid", ["ab", "1maria", "Maria", "maria.souza", "a" * 33, "maria\n"])
def test_validar_uid_rejeita(uid):
    with pytest.raises(DadosInvalidos):
        contas.validar_uid(uid)


def test_validar_org():
    assert contas.validar_org("  CLIENTE-A ") == "CLIENTE-A"
    with pytest.raises(DadosInvalidos):
        contas.validar_org("<x>")


def test_ssha_roundtrip():
    h = contas.hash_ssha("Segredo#1", salt=b"abcd")
    assert h.startswith("{SSHA}")
    assert confere_ssha(h, "Segredo#1")
    assert not confere_ssha(h, "outra")


def test_senha_aleatoria_longa_e_diferente():
    a, b = contas.senha_aleatoria(), contas.senha_aleatoria()
    assert len(a) >= 40 and a != b


def test_problemas_senha():
    assert contas.problemas_senha("Ab1#xy") == []
    assert contas.problemas_senha("abc") == [
        "mínimo de 6 caracteres", "uma letra maiúscula", "um dígito", "um caractere especial",
    ]


def test_atributos_conta_no_padrao():
    attrs = contas.atributos_conta(
        uid="mariasouza", nome="Maria da Silva Souza", cpf=CPF_OK, mail="maria@exemplo.org",
        telefone="+5511912345678", org="CLIENTE-A", uid_number=10070, gid_number=10000,
        senha_hash="{SSHA}xyz", hoje=date(2026, 11, 4),
    )
    assert attrs == {
        "objectClass": ["inetOrgPerson", "posixAccount", "shadowAccount"],
        "uid": "mariasouza", "cn": "Maria Souza", "sn": "Souza", "givenName": "Maria",
        "gecos": "Maria Souza", "uidNumber": "10070", "gidNumber": "10000",
        "homeDirectory": "/home/mariasouza", "loginShell": "/bin/bash",
        "userPassword": "{SSHA}xyz", "shadowLastChange": "20761",
        "shadowMin": "1", "shadowMax": "1825", "shadowWarning": "10", "shadowInactive": "10",
        "mail": "maria@exemplo.org", "telephoneNumber": "+5511912345678",
        "description": f"CPF: {CPF_OK}", "ou": "CLIENTE-A", "o": "CLIENTE-A",
    }


def test_mascarar_email():
    assert contas.mascarar_email("maria@exemplo.org") == "m***@exemplo.org"


def test_validar_formulario_justificativa_opcional():
    base = {"nome": "Maria da Silva Souza", "cpf": "529.982.247-25", "email": "maria@exemplo.org",
            "telefone": "(11) 91234-5678"}
    dados, erros = contas.validar_formulario(base, justificativa_opcional=True)
    assert erros == {} and dados["justificativa"] == ""
    _, erros = contas.validar_formulario({**base, "justificativa": "curta"}, justificativa_opcional=True)
    assert set(erros) == {"justificativa"}
    _, erros = contas.validar_formulario(base)
    assert set(erros) == {"justificativa"}
