import logging

from app.correio import ErroEnvio


def test_falha_de_envio_nao_loga_email_do_destinatario(amb, caplog, monkeypatch):
    def recusar(*a, **k):
        raise ErroEnvio("recusado: maria@exemplo.org")

    monkeypatch.setattr(amb.correio, "enviar", recusar)
    with caplog.at_level(logging.ERROR, logger="ldap-self-signup"):
        ok = amb.app.extensions["signup"].enviar("reset_senha", "maria@exemplo.org",
                                                 nome="M", uid="m", link="L", validade=1)
    assert ok is False
    assert "maria@exemplo.org" not in caplog.text
    assert "m***@exemplo.org" in caplog.text


def test_enviar_entrega_o_email_renderizado_ao_correio(amb):
    ok = amb.app.extensions["signup"].enviar("reset_senha", "maria@exemplo.org",
                                             nome="Maria", uid="m", link="https://cadastro.teste/r/1", validade=1)
    assert ok is True
    [email] = amb.correio.enviados
    assert email["para"] == "maria@exemplo.org" and email["assunto"].endswith("redefinição de senha")
    assert "https://cadastro.teste/r/1" in email["texto"] and ">Redefinir senha</a>" in email["html"]
    assert email["imagens"] == {}
