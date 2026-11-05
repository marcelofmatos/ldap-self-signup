import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from flask import current_app, request

from .contas import mascarar_email
from .correio import ErroEnvio
from .ratelimit import LimiteTaxa

log = logging.getLogger("ldap-self-signup")


def em_thread(funcao: Callable[[], None]) -> None:
    threading.Thread(target=funcao, daemon=True).start()


def na_hora(funcao: Callable[[], None]) -> None:
    funcao()


@dataclass
class Servicos:
    cfg: object
    banco: object
    diretorio: object
    correio: object
    tema: object
    relogio: Callable[[], datetime]
    limite_form: LimiteTaxa
    limite_login: LimiteTaxa
    limite_token: LimiteTaxa
    em_segundo_plano: Callable[[Callable[[], None]], None] = em_thread

    def agora(self) -> datetime:
        return self.relogio()

    def link(self, caminho: str) -> str:
        return self.cfg.public_url + caminho

    def enviar(self, modelo: str, para: str, **ctx) -> bool:
        """Renderiza o e-mail do tema e envia. Falha de SMTP vira False (e log, sem dados pessoais)."""
        email = self.tema.email(modelo, **ctx)
        try:
            self.correio.enviar(para, email)
            return True
        except ErroEnvio as e:
            log.error("falha ao enviar %s para %s: %s", modelo, mascarar_email(para),
                      type(e.__cause__ or e).__name__)
            return False


def svc() -> Servicos:
    return current_app.extensions["signup"]


def ip_cliente() -> str:
    return request.remote_addr or "?"
