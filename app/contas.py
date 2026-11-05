"""Regras puras de conta: validação do formulário, uid, senha e atributos LDAP (sem rede)."""
import base64
import hashlib
import re
import secrets
import unicodedata
from datetime import date

SHADOW = {"shadowMin": "1", "shadowMax": "1825", "shadowWarning": "10", "shadowInactive": "10"}
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
_NOME_RE = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ' -]+$")
_UID_RE = re.compile(r"^[a-z][a-z0-9]{2,31}$")
_ORG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{1,63}$")


class DadosInvalidos(ValueError):
    pass


def sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")


def validar_nome(texto: str) -> str:
    nome = " ".join(texto.split())
    partes = nome.split()
    if not (5 <= len(nome) <= 120) or len(partes) < 2 or min(len(p) for p in partes) < 2 \
            or not _NOME_RE.fullmatch(nome):
        raise DadosInvalidos("Informe nome e sobrenome, só com letras.")
    derivar_nomes(nome)
    return nome


def validar_cpf(texto: str) -> str:
    d = re.sub(r"\D", "", texto)
    if len(d) != 11 or d == d[0] * 11:
        raise DadosInvalidos("CPF inválido.")
    for n in (9, 10):
        soma = sum(int(d[i]) * (n + 1 - i) for i in range(n))
        if (soma * 10) % 11 % 10 != int(d[n]):
            raise DadosInvalidos("CPF inválido.")
    return d


def validar_email(texto: str) -> str:
    email = texto.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email):
        raise DadosInvalidos("E-mail inválido.")
    return email


def normalizar_telefone(texto: str) -> str:
    """Retorna E.164. Sem '+', assume Brasil (DDD + número, com ou sem 55)."""
    d = re.sub(r"\D", "", texto)
    if texto.strip().startswith("+"):
        if not 10 <= len(d) <= 15:
            raise DadosInvalidos("Telefone inválido.")
        return "+" + d
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) not in (10, 11):
        raise DadosInvalidos("Telefone inválido: use DDD + número.")
    return "+55" + d


def validar_justificativa(texto: str) -> str:
    j = texto.strip()
    if not 10 <= len(j) <= 1000:
        raise DadosInvalidos("Conte em poucas palavras por que precisa de acesso (10 a 1000 caracteres).")
    return j


_VALIDADORES = (
    ("nome", validar_nome),
    ("cpf", validar_cpf),
    ("email", validar_email),
    ("telefone", normalizar_telefone),
    ("justificativa", validar_justificativa),
)


def validar_formulario(form: dict, justificativa_opcional: bool = False) -> tuple[dict, dict]:
    """Retorna (dados normalizados, erros por campo). Justificativa opcional: vazia vira ''."""
    dados, erros = {}, {}
    for campo, validar in _VALIDADORES:
        if campo == "justificativa" and justificativa_opcional and not form.get(campo, "").strip():
            dados[campo] = ""
            continue
        try:
            dados[campo] = validar(form.get(campo, ""))
        except DadosInvalidos as e:
            erros[campo] = str(e)
    return dados, erros


def derivar_nomes(nome_completo: str) -> dict:
    """uid = primeiro nome + último sobrenome, minúsculo, ASCII (padrão das contas existentes)."""
    partes = sem_acento(nome_completo).replace("'", "").replace("-", " ").split()
    if len(partes) < 2:
        raise DadosInvalidos("Informe nome e sobrenome, só com letras.")
    primeiro, ultimo = partes[0].capitalize(), partes[-1].capitalize()
    return {"uid": (primeiro + ultimo).lower(), "given_name": primeiro, "sn": ultimo,
            "cn": f"{primeiro} {ultimo}"}


def _normalizado(normalizar, valor: str) -> str:
    try:
        return normalizar(valor)
    except DadosInvalidos:
        return valor


def campos_alterados(conta: dict, dados: dict) -> list[str]:
    """Campos em que os dados (já validados) diferem da conta no LDAP, ambos normalizados.

    O nome compara pelo cn derivado, que é como fica gravado.
    """
    atual = {"nome": _normalizado(lambda n: derivar_nomes(n)["cn"], conta["cn"]), "cpf": conta["cpf"],
             "email": _normalizado(validar_email, conta["mail"]),
             "telefone": _normalizado(normalizar_telefone, conta["telefone"])}
    novo = {**dados, "nome": derivar_nomes(dados["nome"])["cn"]}
    return [c for c in ("nome", "cpf", "email", "telefone") if novo[c] != atual[c]]


def validar_uid(uid: str) -> str:
    if not _UID_RE.fullmatch(uid):
        raise DadosInvalidos("Usuário inválido: 3 a 32 caracteres, minúsculas e dígitos, começando por letra.")
    return uid


def validar_org(org: str) -> str:
    o = " ".join(org.split())
    if not _ORG_RE.fullmatch(o):
        raise DadosInvalidos("Cliente inválido: letras, dígitos, espaço, ponto, hífen ou sublinhado (2 a 64).")
    return o


def hash_ssha(senha: str, salt: bytes | None = None) -> str:
    """{SSHA} = base64(sha1(senha + salt) + salt), formato aceito pelo OpenLDAP."""
    salt = secrets.token_bytes(4) if salt is None else salt
    digest = hashlib.sha1(senha.encode("utf-8") + salt).digest()
    return "{SSHA}" + base64.b64encode(digest + salt).decode("ascii")


def senha_aleatoria() -> str:
    """Senha descartada na criação da conta: ninguém a conhece."""
    return secrets.token_urlsafe(32)


def problemas_senha(senha: str) -> list[str]:
    """Política de senha: mín. 6, maiúscula, minúscula, dígito e especial."""
    problemas = []
    if len(senha) < 6:
        problemas.append("mínimo de 6 caracteres")
    if not any(c.isupper() for c in senha):
        problemas.append("uma letra maiúscula")
    if not any(c.islower() for c in senha):
        problemas.append("uma letra minúscula")
    if not any(c.isdigit() for c in senha):
        problemas.append("um dígito")
    if not any(not c.isalnum() and not c.isspace() for c in senha):
        problemas.append("um caractere especial")
    return problemas


def shadow_last_change(hoje: date | None = None) -> int:
    return ((hoje or date.today()) - date(1970, 1, 1)).days


def atributos_conta(*, uid: str, nome: str, cpf: str, mail: str, telefone: str, org: str,
                    uid_number: int, gid_number: int, senha_hash: str, hoje: date | None = None) -> dict:
    n = derivar_nomes(nome)
    return {
        "objectClass": ["inetOrgPerson", "posixAccount", "shadowAccount"],
        "uid": uid, "cn": n["cn"], "sn": n["sn"], "givenName": n["given_name"], "gecos": n["cn"],
        "uidNumber": str(uid_number), "gidNumber": str(gid_number),
        "homeDirectory": f"/home/{uid}", "loginShell": "/bin/bash",
        "userPassword": senha_hash, "shadowLastChange": str(shadow_last_change(hoje)),
        **SHADOW,
        "mail": mail, "telephoneNumber": telefone, "description": f"CPF: {cpf}",
        "ou": org, "o": org,
    }


def mascarar_email(email: str) -> str:
    local, _, dominio = email.partition("@")
    return f"{local[:1]}***@{dominio}"
