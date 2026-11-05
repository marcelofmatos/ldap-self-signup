from datetime import datetime, timedelta, timezone

import pytest

from app import tokens
from app.banco import Banco

AGORA = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def test_token_so_hash_no_banco(banco):
    t = tokens.emitir(banco, tokens.DEFINIR_SENHA, "mariasouza", 24, AGORA)
    assert len(t) >= 40
    assert banco.obter_token(t) is None
    assert banco.obter_token(tokens.hash_token(t))["alvo"] == "mariasouza"


def test_validar_nao_consome_e_consumir_uma_vez(banco):
    t = tokens.emitir(banco, tokens.DEFINIR_SENHA, "mariasouza", 24, AGORA)
    assert tokens.validar(banco, t, tokens.DEFINIR_SENHA, AGORA) == "mariasouza"
    assert tokens.validar(banco, t, tokens.DEFINIR_SENHA, AGORA) == "mariasouza"
    assert tokens.consumir(banco, t, tokens.DEFINIR_SENHA, AGORA) == "mariasouza"
    assert tokens.consumir(banco, t, tokens.DEFINIR_SENHA, AGORA) is None


def test_expirado(banco):
    t = tokens.emitir(banco, tokens.CONFIRMAR_EMAIL, "sol:1", 24, AGORA)
    assert tokens.validar(banco, t, tokens.CONFIRMAR_EMAIL, AGORA + timedelta(hours=24)) is None


def test_finalidade_errada(banco):
    t = tokens.emitir(banco, tokens.CONFIRMAR_EMAIL, "sol:1", 24, AGORA)
    assert tokens.validar(banco, t, tokens.DEFINIR_SENHA, AGORA) is None


def test_token_inexistente(banco):
    assert tokens.validar(banco, "nada", tokens.DEFINIR_SENHA, AGORA) is None


def test_novo_definir_senha_invalida_anterior(banco):
    t1 = tokens.emitir(banco, tokens.DEFINIR_SENHA, "mariasouza", 24, AGORA)
    t2 = tokens.emitir(banco, tokens.DEFINIR_SENHA, "mariasouza", 24, AGORA)
    assert tokens.validar(banco, t1, tokens.DEFINIR_SENHA, AGORA) is None
    assert tokens.validar(banco, t2, tokens.DEFINIR_SENHA, AGORA) == "mariasouza"


def test_novo_convite_invalida_anterior(banco):
    t1 = tokens.emitir(banco, tokens.CONVITE, "sol:1", 24 * 7, AGORA)
    t2 = tokens.emitir(banco, tokens.CONVITE, "sol:1", 24 * 7, AGORA)
    assert tokens.validar(banco, t1, tokens.CONVITE, AGORA) is None
    assert tokens.validar(banco, t2, tokens.CONVITE, AGORA + timedelta(days=6)) == "sol:1"
    assert tokens.validar(banco, t2, tokens.CONVITE, AGORA + timedelta(days=7)) is None


def test_nova_confirmacao_de_email_invalida_anterior(banco):
    t1 = tokens.emitir(banco, tokens.CONFIRMAR_EMAIL, "sol:1", 24, AGORA)
    t2 = tokens.emitir(banco, tokens.CONFIRMAR_EMAIL, "sol:1", 24, AGORA)
    assert tokens.validar(banco, t1, tokens.CONFIRMAR_EMAIL, AGORA) is None
    assert tokens.validar(banco, t2, tokens.CONFIRMAR_EMAIL, AGORA) == "sol:1"
