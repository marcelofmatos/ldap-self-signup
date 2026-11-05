import smtplib
import ssl
from email.message import EmailMessage


class ErroEnvio(Exception):
    pass


class Correio:
    def __init__(self, cfg):
        self.cfg = cfg

    def _contexto_tls(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        if not self.cfg.smtp_tls_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def enviar(self, para: str, email) -> None:
        """multipart/alternative: texto + HTML; com imagens, o HTML vira multipart/related (cid:<id>)."""
        msg = EmailMessage()
        msg["From"] = self.cfg.smtp_from
        msg["To"] = para
        msg["Subject"] = email.assunto
        msg.set_content(email.texto)
        msg.add_alternative(email.html, subtype="html")
        parte_html = msg.get_payload()[1]
        for cid, (dados, subtipo) in email.imagens.items():
            parte_html.add_related(dados, maintype="image", subtype=subtipo, cid=f"<{cid}>",
                                   disposition="inline", filename=f"{cid}.{subtipo}")
        if self.cfg.smtp_user and not self.cfg.smtp_starttls:
            raise ErroEnvio("login SMTP sem TLS recusado")
        try:
            with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=15) as smtp:
                if self.cfg.smtp_starttls:
                    smtp.starttls(context=self._contexto_tls())
                if self.cfg.smtp_user:
                    smtp.login(self.cfg.smtp_user, self.cfg.smtp_password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as e:
            raise ErroEnvio(str(e)) from e
