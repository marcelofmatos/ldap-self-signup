"""Tokens de uso único: o valor em claro só existe no e-mail; o banco guarda o SHA-256."""
import hashlib
import secrets
from datetime import datetime, timedelta

from .banco import iso

CONFIRMAR_EMAIL = "confirmar_email"
DEFINIR_SENHA = "definir_senha"
CONFIRMAR_DADOS = "confirmar_dados"
CONVITE = "convite"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def emitir(banco, finalidade: str, alvo: str, ttl_horas: int, agora: datetime, *,
           invalidar_anteriores: bool = True) -> str:
    if invalidar_anteriores and finalidade in (DEFINIR_SENHA, CONVITE, CONFIRMAR_EMAIL, CONFIRMAR_DADOS):
        banco.invalidar_tokens(finalidade, alvo, agora)
    token = secrets.token_urlsafe(32)
    banco.inserir_token(hash_token(token), finalidade, alvo, iso(agora + timedelta(hours=ttl_horas)))
    return token


def validar(banco, token: str, finalidade: str, agora: datetime) -> str | None:
    """Retorna o alvo se o token existe, é da finalidade, não foi usado e não expirou."""
    reg = banco.obter_token(hash_token(token))
    if not reg or reg["finalidade"] != finalidade or reg["usado_em"] or reg["expira_em"] <= iso(agora):
        return None
    return reg["alvo"]


def consumir(banco, token: str, finalidade: str, agora: datetime) -> str | None:
    alvo = validar(banco, token, finalidade, agora)
    if alvo is None or not banco.marcar_token_usado(hash_token(token), agora):
        return None
    return alvo
