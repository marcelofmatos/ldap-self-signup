import smtplib
import ssl
from types import SimpleNamespace

import pytest

from app.correio import Correio, ErroEnvio
from app.tema import Email


class SMTPFalso:
    instancias = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.chamadas, self.msg = host, port, [], None
        SMTPFalso.instancias.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.contexto = context
        self.chamadas.append("starttls")

    def login(self, u, p):
        self.chamadas.append(("login", u, p))

    def send_message(self, msg):
        self.msg = msg


def _cfg(**over):
    base = dict(smtp_host="smtp.x", smtp_port=1025, smtp_user="", smtp_password="",
                smtp_from="cadastro@x", smtp_starttls=False, smtp_tls_verify=True)
    base.update(over)
    return SimpleNamespace(**base)


EMAIL = Email("A", "t", "<p>t</p>", {})


def test_envia_multipart(monkeypatch):
    SMTPFalso.instancias.clear()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    Correio(_cfg()).enviar("maria@x", Email("Assunto", "texto", "<p>texto</p>", {}))
    s = SMTPFalso.instancias[0]
    assert (s.host, s.port, s.chamadas) == ("smtp.x", 1025, [])
    assert s.msg["To"] == "maria@x" and s.msg["From"] == "cadastro@x" and s.msg["Subject"] == "Assunto"
    assert s.msg.get_content_type() == "multipart/alternative"
    texto, html = s.msg.get_payload()
    assert texto.get_content_type() == "text/plain" and texto.get_content().strip() == "texto"
    assert html.get_content_type() == "text/html" and html.get_content().strip() == "<p>texto</p>"


def test_logo_vai_como_parte_relacionada(monkeypatch):
    SMTPFalso.instancias.clear()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    email = Email("A", "t", '<img src="cid:logo">', {"logo": (b"\x89PNG-logo", "png")})
    Correio(_cfg()).enviar("maria@x", email)
    msg = SMTPFalso.instancias[0].msg
    assert msg.get_content_type() == "multipart/alternative"
    texto, relacionado = msg.get_payload()
    assert texto.get_content_type() == "text/plain"
    assert relacionado.get_content_type() == "multipart/related"
    html, imagem = relacionado.get_payload()
    assert html.get_content_type() == "text/html" and 'src="cid:logo"' in html.get_content()
    assert imagem.get_content_type() == "image/png" and imagem["Content-ID"] == "<logo>"
    assert imagem.get_content() == b"\x89PNG-logo"


def test_starttls_e_login(monkeypatch):
    SMTPFalso.instancias.clear()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    Correio(_cfg(smtp_starttls=True, smtp_user="u", smtp_password="p")).enviar("m@x", EMAIL)
    assert SMTPFalso.instancias[0].chamadas == ["starttls", ("login", "u", "p")]


def test_falha_vira_erro_envio(monkeypatch):
    def quebra(*a, **k):
        raise OSError("conexão recusada")
    monkeypatch.setattr(smtplib, "SMTP", quebra)
    with pytest.raises(ErroEnvio):
        Correio(_cfg()).enviar("m@x", EMAIL)


def test_starttls_verifica_certificado_por_padrao(monkeypatch):
    SMTPFalso.instancias.clear()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    Correio(_cfg(smtp_starttls=True)).enviar("m@x", EMAIL)
    ctx = SMTPFalso.instancias[0].contexto
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_starttls_sem_verificacao_quando_desligada(monkeypatch):
    SMTPFalso.instancias.clear()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    Correio(_cfg(smtp_starttls=True, smtp_tls_verify=False)).enviar("m@x", EMAIL)
    ctx = SMTPFalso.instancias[0].contexto
    assert ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False


def test_login_sem_tls_e_recusado(monkeypatch):
    SMTPFalso.instancias.clear()
    monkeypatch.setattr(smtplib, "SMTP", SMTPFalso)
    with pytest.raises(ErroEnvio, match="sem TLS"):
        Correio(_cfg(smtp_user="u", smtp_password="p")).enviar("m@x", EMAIL)
    assert SMTPFalso.instancias == []
