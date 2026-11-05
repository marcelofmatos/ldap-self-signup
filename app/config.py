import logging
import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import contas

log = logging.getLogger("ldap-self-signup")


class ErroConfig(ValueError):
    pass


_UNIDADES = {"s": 1, "min": 60, "hora": 3600, "dia": 86400}


def parse_limite(texto: str) -> tuple[int, int]:
    """'5/hora' -> (5, 3600); '10/15min' -> (10, 900)."""
    m = re.fullmatch(r"(\d+)/(\d*)(s|min|hora|dia)", texto.strip())
    if not m:
        raise ErroConfig(f"limite inválido: {texto!r} (ex.: 5/hora, 10/15min)")
    return int(m[1]), int(m[2] or 1) * _UNIDADES[m[3]]


@dataclass(frozen=True)
class Config:
    public_url: str
    ldap_url: str
    ldap_bind_dn: str
    ldap_bind_pw: str = field(repr=False)
    ldap_users_base: str
    ldap_default_group_dn: str
    ldap_default_gid: int
    admin_notify_email: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str = field(repr=False)
    smtp_from: str
    smtp_starttls: bool
    secret_key: str = field(repr=False)
    data_dir: Path
    template_dir: Path
    token_ttl_hours: int = 24
    convite_ttl_dias: int = 7
    rate_limit_form: tuple[int, int] = (10, 3600)
    rate_limit_login: tuple[int, int] = (10, 900)
    trusted_proxies: int = 1
    cookie_secure: bool = True
    smtp_tls_verify: bool = True
    admin_group_dn: str = ""
    admin_uids: tuple[str, ...] = ()
    timezone_exibicao: str = "America/Sao_Paulo"


LDAP_CONFIG_PADRAO = Path("/config/ldap.toml")


def _ler(caminho: Path, rotulo: str) -> str:
    """Lê um arquivo de config/segredo; o erro cita só o caminho, nunca o conteúdo."""
    try:
        return caminho.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        raise ErroConfig(f"não foi possível ler {rotulo}: {caminho}") from None


def _segredo(env, nome: str, obrigatorio: bool = True) -> str:
    """Segredos só por arquivo (<NOME>_FILE, ex.: Docker secret)."""
    arquivo = env.get(f"{nome}_FILE", "").strip()
    if arquivo:
        valor = _ler(Path(arquivo), f"{nome}_FILE").strip()
        if obrigatorio and not valor:
            raise ErroConfig(f"segredo vazio: {nome}_FILE")
        return valor
    if obrigatorio:
        raise ErroConfig(f"variável obrigatória ausente: {nome}_FILE")
    return ""


def _uids(valores, origem: str) -> tuple[str, ...]:
    uids = []
    for bruto in valores:
        uid = bruto.strip().lower()
        try:
            uids.append(contas.validar_uid(uid))
        except contas.DadosInvalidos as e:
            raise ErroConfig(f"{origem}: uid inválido {uid!r}: {e}") from e
    return tuple(uids)


_ESQUEMA_TOML = {
    "servidor": {"url", "bind_dn", "bind_pw_file"},
    "contas": {"base", "grupo_padrao", "gid_padrao"},
    "admins": {"uids", "grupo"},
}


def _ldap_do_arquivo(caminho: Path) -> dict:
    try:
        dados = tomllib.loads(_ler(caminho, "o arquivo de configuração do LDAP"))
    except tomllib.TOMLDecodeError as e:
        raise ErroConfig(f"{caminho}: TOML inválido: {e}") from e
    if "bind_pw" in dados or any(isinstance(v, dict) and "bind_pw" in v for v in dados.values()):
        raise ErroConfig("senha não pode ficar no ldap.toml; use bind_pw_file")
    for secao, valores in dados.items():
        if not isinstance(valores, dict):
            raise ErroConfig(f"{caminho}: chave desconhecida: {secao}")
        if secao not in _ESQUEMA_TOML:
            raise ErroConfig(f"{caminho}: seção desconhecida: [{secao}]")
        for chave in valores.keys() - _ESQUEMA_TOML[secao]:
            raise ErroConfig(f"{caminho}: chave desconhecida: {secao}.{chave}")

    def texto(secao: str, chave: str, obrigatorio: bool = True) -> str:
        valor = dados.get(secao, {}).get(chave, "")
        if not isinstance(valor, str):
            raise ErroConfig(f"{caminho}: {secao}.{chave} deve ser texto")
        valor = valor.strip()
        if obrigatorio and not valor:
            raise ErroConfig(f"{caminho}: chave obrigatória ausente: {secao}.{chave}")
        return valor

    senha = _ler(Path(texto("servidor", "bind_pw_file")), "servidor.bind_pw_file").strip()
    if not senha:
        raise ErroConfig(f"segredo vazio: servidor.bind_pw_file de {caminho}")
    gid = dados.get("contas", {}).get("gid_padrao", 10000)
    if not isinstance(gid, int) or isinstance(gid, bool):
        raise ErroConfig(f"{caminho}: contas.gid_padrao deve ser inteiro")
    uids = dados.get("admins", {}).get("uids", [])
    if not isinstance(uids, list) or not all(isinstance(u, str) for u in uids):
        raise ErroConfig(f"{caminho}: admins.uids deve ser uma lista de textos")
    return dict(
        ldap_url=texto("servidor", "url"),
        ldap_bind_dn=texto("servidor", "bind_dn"),
        ldap_bind_pw=senha,
        ldap_users_base=texto("contas", "base"),
        ldap_default_group_dn=texto("contas", "grupo_padrao"),
        ldap_default_gid=gid,
        admin_group_dn=texto("admins", "grupo", obrigatorio=False),
        admin_uids=_uids(uids, f"{caminho}: admins.uids"),
    )


def carregar_config(env=None) -> Config:
    env = os.environ if env is None else env

    def req(nome: str) -> str:
        valor = env.get(nome, "").strip()
        if not valor:
            raise ErroConfig(f"variável obrigatória ausente: {nome}")
        return valor

    explicito = env.get("LDAP_CONFIG", "").strip()
    caminho = Path(explicito) if explicito else LDAP_CONFIG_PADRAO
    if explicito and not caminho.exists():
        raise ErroConfig(f"LDAP_CONFIG aponta para arquivo inexistente: {caminho}")
    if caminho.exists() and not caminho.is_file():
        raise ErroConfig(f"{caminho} não é um arquivo")
    if caminho.exists():
        ldap = _ldap_do_arquivo(caminho)
        log.info("configuração de LDAP lida de %s (variáveis LDAP_*/ADMIN_GROUP_DN/ADMIN_UIDS ignoradas)",
                 caminho)
    else:
        ldap = dict(
            ldap_url=req("LDAP_URL"),
            ldap_bind_dn=req("LDAP_BIND_DN"),
            ldap_bind_pw=_segredo(env, "LDAP_BIND_PW"),
            ldap_users_base=req("LDAP_USERS_BASE"),
            ldap_default_group_dn=req("LDAP_DEFAULT_GROUP_DN"),
            ldap_default_gid=int(env.get("LDAP_DEFAULT_GID", "10000")),
            admin_group_dn=env.get("ADMIN_GROUP_DN", "").strip(),
            admin_uids=_uids([u for u in env.get("ADMIN_UIDS", "").split(",") if u.strip()], "ADMIN_UIDS"),
        )
    if not ldap["admin_uids"] and not ldap["admin_group_dn"]:
        raise ErroConfig("configure ADMIN_UIDS/[admins].uids ou ADMIN_GROUP_DN/[admins].grupo")

    def booleano(nome: str, padrao: str) -> bool:
        valor = env.get(nome, padrao).strip().lower()
        if valor not in ("true", "false"):
            raise ErroConfig(f"{nome} deve ser true ou false, recebido: {valor!r}")
        return valor == "true"

    fuso = env.get("TIMEZONE_EXIBICAO", "").strip() or "America/Sao_Paulo"
    try:
        ZoneInfo(fuso)
    except (ZoneInfoNotFoundError, ValueError):
        raise ErroConfig(f"TIMEZONE_EXIBICAO inválido: {fuso!r} (ex.: America/Sao_Paulo)") from None

    try:
        convite_ttl_dias = int(env.get("CONVITE_TTL_DIAS", "7").strip())
    except ValueError:
        convite_ttl_dias = 0
    if convite_ttl_dias < 1:
        raise ErroConfig(f"CONVITE_TTL_DIAS deve ser um inteiro >= 1, recebido: {env.get('CONVITE_TTL_DIAS')!r}")

    return Config(
        public_url=req("PUBLIC_URL").rstrip("/"),
        **ldap,
        admin_notify_email=req("ADMIN_NOTIFY_EMAIL"),
        smtp_host=req("SMTP_HOST"),
        smtp_port=int(env.get("SMTP_PORT", "587")),
        smtp_user=env.get("SMTP_USER", ""),
        smtp_password=_segredo(env, "SMTP_PASSWORD", obrigatorio=False),
        smtp_from=req("SMTP_FROM"),
        smtp_starttls=booleano("SMTP_STARTTLS", "true"),
        secret_key=_segredo(env, "SECRET_KEY"),
        data_dir=Path(env.get("DATA_DIR", "/data")),
        template_dir=Path(env.get("TEMPLATE_DIR", "/template")),
        token_ttl_hours=int(env.get("TOKEN_TTL_HOURS", "24")),
        convite_ttl_dias=convite_ttl_dias,
        rate_limit_form=parse_limite(env.get("RATE_LIMIT_FORM", "10/hora")),
        rate_limit_login=parse_limite(env.get("RATE_LIMIT_LOGIN", "10/15min")),
        trusted_proxies=int(env.get("TRUSTED_PROXIES", "1")),
        cookie_secure=booleano("COOKIE_SECURE", "true"),
        smtp_tls_verify=booleano("SMTP_TLS_VERIFY", "true"),
        timezone_exibicao=fuso,
    )
