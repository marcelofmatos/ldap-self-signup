import base64
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import contas
from app.config import Config
from app.correio import ErroEnvio
from app.diretorio import ErroDiretorio


def config_teste(tmp_path: Path, **over) -> Config:
    base = dict(
        public_url="https://cadastro.teste",
        ldap_url="ldap://openldap:389",
        ldap_bind_dn="cn=admin,dc=exemplo,dc=org",
        ldap_bind_pw="admin-teste",
        ldap_users_base="ou=Users,dc=exemplo,dc=org",
        ldap_default_group_dn="cn=Usuario,ou=Groups,dc=exemplo,dc=org",
        ldap_default_gid=10000,
        admin_group_dn="cn=Cadastro Admins,ou=Groups,dc=exemplo,dc=org",
        admin_notify_email="admin@teste.local",
        smtp_host="localhost", smtp_port=1025, smtp_user="", smtp_password="",
        smtp_from="cadastro@teste.local", smtp_starttls=False,
        secret_key="segredo-de-teste",
        data_dir=tmp_path / "data", template_dir=tmp_path / "template",
        trusted_proxies=0, cookie_secure=False,
    )
    base.update(over)
    return Config(**base)


class FakeDiretorio:
    def __init__(self):
        self.contas = {}  # uid -> dict(uid, cn, mail, ou, cpf, telefone, senha[, grupos])
        self.admins = {"chefe": "Chefe#123"}
        self.falhar = False
        self.falhar_criacao = False

    def _checar(self):
        if self.falhar:
            raise ErroDiretorio("ldap fora do ar")

    def autenticar_admin(self, uid, senha):
        self._checar()
        return bool(senha) and self.admins.get(uid) == senha

    def e_admin(self, uid):
        self._checar()
        return uid in self.admins

    def autenticar(self, uid, senha):
        self._checar()
        c = self.contas.get(uid)
        return bool(senha) and c is not None and c.get("senha") == senha

    def grupos_de(self, uid):
        self._checar()
        return sorted(self.contas.get(uid, {}).get("grupos", []), key=str.lower)

    def conflitos(self, uid, cpf, mail):
        self._checar()
        return {"uid": [u for u in self.contas if u == uid],
                "cpf": [u for u, c in self.contas.items() if c["cpf"] == cpf],
                "mail": [u for u, c in self.contas.items() if c["mail"] == mail]}

    def organizacoes(self):
        self._checar()
        return sorted({c["ou"] for c in self.contas.values() if c["ou"]}, key=str.lower)

    def listar_contas(self):
        self._checar()
        return [{**self.obter_conta(u), "cpf": self.contas[u]["cpf"],
                 "grupos": sorted(self.contas[u].get("grupos", []), key=str.lower)} for u in sorted(self.contas)]

    def contas_por_email(self, mail):
        self._checar()
        return [{k: c.get(k, "") for k in ("uid", "cn", "mail", "ou")}
                for u, c in sorted(self.contas.items()) if c.get("mail", "").lower() == mail.lower()]

    def obter_conta(self, uid):
        self._checar()
        c = self.contas.get(uid)
        return {k: c.get(k, "") for k in ("uid", "cn", "mail", "ou", "cpf", "telefone")} if c else None

    def atualizar_dados(self, uid, *, nome, cpf, mail, telefone):
        self._checar()
        if self.falhar_criacao:
            raise ErroDiretorio("ldap fora do ar")
        if uid not in self.contas:
            raise ErroDiretorio(f"conta {uid} não encontrada")
        self.contas[uid].update(cn=contas.derivar_nomes(nome)["cn"], cpf=cpf, mail=mail, telefone=telefone)

    def definir_email(self, uid, email):
        self._checar()
        if uid not in self.contas:
            raise ErroDiretorio(f"conta {uid} não encontrada")
        self.contas[uid]["mail"] = email

    def criar_conta(self, *, uid, nome, cpf, mail, telefone, org, hoje=None):
        self._checar()
        if self.falhar_criacao:
            raise ErroDiretorio("ldap fora do ar")
        if uid in self.contas:
            raise ErroDiretorio(f"o usuário {uid} já existe")
        self.contas[uid] = dict(uid=uid, cn=nome, mail=mail, ou=org, cpf=cpf, telefone=telefone, senha=None)
        return 10000 + len(self.contas)

    def definir_senha(self, uid, senha, hoje=None):
        self._checar()
        self.contas[uid]["senha"] = senha


class FakeCorreio:
    def __init__(self):
        self.enviados = []
        self.falhar = False

    def enviar(self, para, email):
        if self.falhar:
            raise ErroEnvio("smtp fora do ar")
        self.enviados.append(dict(para=para, assunto=email.assunto, texto=email.texto, html=email.html,
                                  imagens=email.imagens))

    def caminho_do_link(self, indice=-1):
        """Caminho (sem o host) do 1º link do e-mail."""
        url = re.search(r"https://cadastro\.teste([^\s>]+)", self.enviados[indice]["texto"]).group(1)
        return url


class Relogio:
    def __init__(self):
        self.agora = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.agora

    def avancar(self, **kw):
        self.agora += timedelta(**kw)


def template_teste(tmp_path: Path) -> Path:
    d = tmp_path / "template"
    d.mkdir(exist_ok=True)
    (d / "privacidade.md").write_text("# Aviso de privacidade\n\nUsamos seus dados para criar sua conta.\n",
                                      encoding="utf-8")
    return d


def auditoria(banco) -> list[dict]:
    """Registros de auditoria, do mais recente para o mais antigo."""
    with sqlite3.connect(banco.caminho) as con:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute("SELECT * FROM auditoria ORDER BY id DESC")]


def texto_aviso(banco, versao: str) -> str | None:
    with sqlite3.connect(banco.caminho) as con:
        row = con.execute("SELECT texto FROM avisos WHERE versao=?", (versao,)).fetchone()
    return row[0] if row else None


def confere_ssha(hash_str: str, senha: str) -> bool:
    if not hash_str.startswith("{SSHA}"):
        return False
    bruto = base64.b64decode(hash_str[len("{SSHA}"):])
    return hashlib.sha1(senha.encode("utf-8") + bruto[20:]).digest() == bruto[:20]
