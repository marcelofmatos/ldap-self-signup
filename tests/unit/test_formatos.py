from zoneinfo import ZoneInfo

import pytest

from app import formatos

SP = ZoneInfo("America/Sao_Paulo")


@pytest.mark.parametrize("valor,esperado", [
    ("2026-11-04T20:01:56+00:00", "04/11/2026 17:01"),
    ("2026-01-01T02:30:00+00:00", "31/12/2025 23:30"),
    ("2026-11-04T20:01:56", "04/11/2026 17:01"),  # sem fuso = UTC
    ("", ""),
    (None, ""),
    ("não é data", "não é data"),
])
def test_data(valor, esperado):
    assert formatos.data(valor, SP) == esperado


def test_data_respeita_o_fuso():
    assert formatos.data("2026-11-04T20:01:56+00:00", ZoneInfo("UTC")) == "04/11/2026 20:01"


@pytest.mark.parametrize("valor,esperado", [
    ("52998224725", "529.982.247-25"),
    ("529.982.247-25", "529.982.247-25"),
    ("123", "123"),
    ("", ""),
    (None, ""),
])
def test_cpf(valor, esperado):
    assert formatos.cpf(valor) == esperado


@pytest.mark.parametrize("valor,esperado", [
    ("+5511912345678", "+55 (11) 91234-5678"),
    ("+551134567890", "+55 (11) 3456-7890"),
    ("+14155550100", "+14155550100"),
    ("", ""),
    (None, ""),
])
def test_telefone(valor, esperado):
    assert formatos.telefone(valor) == esperado


def test_cpf_mascarado():
    assert formatos.cpf_mascarado("52998224725") == "***.982.247-**"
    assert formatos.cpf_mascarado("") == ""
    assert formatos.cpf_mascarado("123") == "***"
    assert formatos.cpf_mascarado("529.982.247-25") == "***.982.247-**"
    assert formatos.cpf_mascarado(None) == ""
