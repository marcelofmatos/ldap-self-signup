"""Acesso ao OpenLDAP via ldap3. Filtros e RDNs sempre escapados."""
import re
import threading
from datetime import date

from ldap3 import BASE, MODIFY_ADD, MODIFY_REPLACE, NONE, SUBTREE, Connection, Server
from ldap3.core.exceptions import (LDAPAttributeOrValueExistsResult, LDAPBindError, LDAPException,
                                 LDAPInvalidCredentialsResult)
from ldap3.utils.conv import escape_filter_chars as esc
from ldap3.utils.dn import escape_rdn, to_dn

from . import contas

_LOCK_CRIACAO = threading.Lock()


class ErroDiretorio(Exception):
    pass


def _v(attrs: dict, chave: str) -> str:
    valores = _lista(attrs, chave)
    return valores[0] if valores else ""


def _cpf(attrs: dict) -> str:
    achado = re.search(r"CPF:\s*(\d{11})", " ".join(_lista(attrs, "description")))
    return achado.group(1) if achado else ""


def _lista(attrs: dict, chave: str) -> list[str]:
    valores = attrs.get(chave) or []
    return [str(valores)] if isinstance(valores, str) else [str(v) for v in valores]


class Diretorio:
    def __init__(self, cfg):
        self.cfg = cfg
        self.servidor = Server(cfg.ldap_url, get_info=NONE, connect_timeout=10)

    def _con(self, dn: str | None = None, senha: str | None = None) -> Connection:
        if dn is None:
            dn, senha = self.cfg.ldap_bind_dn, self.cfg.ldap_bind_pw
        return Connection(self.servidor, user=dn, password=senha, auto_bind=True,
                          raise_exceptions=True, receive_timeout=15)

    def _buscar(self, con, filtro: str, attrs: list[str]) -> list[tuple[str, dict]]:
        con.search(self.cfg.ldap_users_base, filtro, SUBTREE, attributes=attrs)
        return [(e.entry_dn, e.entry_attributes_as_dict) for e in con.entries]

    def _dn_de(self, con, uid: str) -> str | None:
        achados = self._buscar(con, f"(uid={esc(uid)})", ["uid"])
        return achados[0][0] if len(achados) == 1 else None

    def autenticar_admin(self, uid: str, senha: str) -> bool:
        if not uid or not senha:
            return False
        try:
            with self._con() as con:
                dn = self._dn_de(con, uid)
                if dn is None:
                    return False
                if uid not in self.cfg.admin_uids:
                    if not self.cfg.admin_group_dn:
                        return False
                    con.search(self.cfg.admin_group_dn, f"(memberUid={esc(uid)})", BASE, attributes=["cn"])
                    if not con.entries:
                        return False
            try:
                with self._con(dn, senha):
                    return True
            except (LDAPBindError, LDAPInvalidCredentialsResult):
                return False
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e

    def autenticar(self, uid: str, senha: str) -> bool:
        """Usuário e senha conferem (bind com o DN da conta). Não exige grupo."""
        if not uid or not senha:
            return False
        try:
            with self._con() as con:
                dn = self._dn_de(con, uid)
            if dn is None:
                return False
            try:
                with self._con(dn, senha):
                    return True
            except (LDAPBindError, LDAPInvalidCredentialsResult):
                return False
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e

    def grupos_de(self, uid: str) -> list[str]:
        """cn dos posixGroups em que o uid é memberUid, em ordem alfabética."""
        base_grupos = ",".join(to_dn(self.cfg.ldap_default_group_dn)[1:])
        try:
            with self._con() as con:
                grupos = self._paginada(con, base_grupos, f"(&(objectClass=posixGroup)(memberUid={esc(uid)}))",
                                        ["cn"])
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e
        return sorted((_v(g, "cn") for g in grupos), key=str.lower)

    def conflitos(self, uid: str, cpf: str, mail: str) -> dict:
        try:
            with self._con() as con:
                return {
                    "uid": [_v(a, "uid") for _, a in self._buscar(con, f"(uid={esc(uid)})", ["uid"])],
                    "cpf": [_v(a, "uid") for _, a in
                            self._buscar(con, f"(description=CPF: {esc(cpf)})", ["uid"])],
                    "mail": [_v(a, "uid") for _, a in self._buscar(con, f"(mail={esc(mail)})", ["uid"])],
                }
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e

    def organizacoes(self) -> list[str]:
        try:
            with self._con() as con:
                # só contas: a própria entrada ou=Users (base da busca) também tem "ou"
                achados = self._buscar(con, "(&(objectClass=posixAccount)(ou=*))", ["ou"])
                valores = {str(v) for _, a in achados for v in a.get("ou", [])}
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e
        return sorted(valores, key=str.lower)

    def _resumo(self, attrs: dict) -> dict:
        return {"uid": _v(attrs, "uid"), "cn": _v(attrs, "cn"), "mail": _v(attrs, "mail"), "ou": _v(attrs, "ou")}

    def _paginada(self, con, base: str, filtro: str, attrs: list[str]) -> list[dict]:
        achados = con.extend.standard.paged_search(base, filtro, SUBTREE, attributes=attrs, paged_size=500,
                                                   generator=False)
        return [e["attributes"] for e in achados if e.get("type") == "searchResEntry"]

    def listar_contas(self) -> list[dict]:
        """Todas as contas (posixAccount), ordenadas por uid, com o cn dos posixGroups de que são memberUid."""
        base_grupos = ",".join(to_dn(self.cfg.ldap_default_group_dn)[1:])
        try:
            with self._con() as con:
                pessoas = self._paginada(con, self.cfg.ldap_users_base, "(objectClass=posixAccount)",
                                         ["uid", "cn", "mail", "ou", "description"])
                grupos = self._paginada(con, base_grupos, "(objectClass=posixGroup)", ["cn", "memberUid"])
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e
        por_uid: dict[str, list[str]] = {}
        for g in grupos:
            for membro in _lista(g, "memberUid"):
                por_uid.setdefault(membro, []).append(_v(g, "cn"))
        contas_ = []
        for a in pessoas:
            conta = {**self._resumo(a), "cpf": _cpf(a)}
            conta["grupos"] = sorted(por_uid.get(conta["uid"], []), key=str.lower)
            contas_.append(conta)
        return sorted(contas_, key=lambda c: c["uid"])

    def contas_por_email(self, mail: str) -> list[dict]:
        """Contas (uid, cn, mail, ou) com este e-mail; o atributo mail do LDAP não diferencia maiúsculas."""
        try:
            with self._con() as con:
                achados = self._buscar(con, f"(&(objectClass=posixAccount)(mail={esc(mail)}))",
                                       ["uid", "cn", "mail", "ou"])
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e
        return sorted((self._resumo(a) for _, a in achados), key=lambda c: c["uid"])

    def obter_conta(self, uid: str) -> dict | None:
        try:
            with self._con() as con:
                achados = self._buscar(con, f"(uid={esc(uid)})",
                                       ["uid", "cn", "mail", "ou", "description", "telephoneNumber"])
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e
        if len(achados) != 1:
            return None
        a = achados[0][1]
        return {**self._resumo(a), "cpf": _cpf(a), "telefone": _v(a, "telephoneNumber")}

    def atualizar_dados(self, uid: str, *, nome: str, cpf: str, mail: str, telefone: str) -> None:
        """Atualiza nome (cn/sn/givenName/gecos), a linha CPF da description, mail e telefone. uid/ou não mudam."""
        n = contas.derivar_nomes(nome)
        try:
            with self._con() as con:
                achados = self._buscar(con, f"(uid={esc(uid)})", ["description"])
                if len(achados) != 1:
                    raise ErroDiretorio(f"conta {uid} não encontrada")
                dn, attrs = achados[0]
                descricoes = [d for d in _lista(attrs, "description") if not d.startswith("CPF:")]
                con.modify(dn, {
                    "cn": [(MODIFY_REPLACE, [n["cn"]])], "sn": [(MODIFY_REPLACE, [n["sn"]])],
                    "givenName": [(MODIFY_REPLACE, [n["given_name"]])], "gecos": [(MODIFY_REPLACE, [n["cn"]])],
                    "description": [(MODIFY_REPLACE, [*descricoes, f"CPF: {cpf}"])],
                    "mail": [(MODIFY_REPLACE, [mail])], "telephoneNumber": [(MODIFY_REPLACE, [telefone])],
                })
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e

    def criar_conta(self, *, uid: str, nome: str, cpf: str, mail: str, telefone: str, org: str,
                    hoje: date | None = None) -> int:
        """Cria a conta com senha aleatória descartada e a põe no grupo padrão. Retorna o uidNumber."""
        with _LOCK_CRIACAO:
            try:
                with self._con() as con:
                    if self._buscar(con, f"(uid={esc(uid)})", ["uid"]):
                        raise ErroDiretorio(f"o usuário {uid} já existe")
                    numeros = [int(_v(a, "uidNumber")) for _, a in
                               self._buscar(con, "(uidNumber=*)", ["uidNumber"])]
                    uid_number = max(numeros, default=10000) + 1
                    attrs = contas.atributos_conta(
                        uid=uid, nome=nome, cpf=cpf, mail=mail, telefone=telefone, org=org,
                        uid_number=uid_number, gid_number=self.cfg.ldap_default_gid,
                        senha_hash=contas.hash_ssha(contas.senha_aleatoria()), hoje=hoje)
                    dn = f"uid={escape_rdn(uid)},{self.cfg.ldap_users_base}"
                    con.add(dn, attributes=attrs)
                    try:
                        con.modify(self.cfg.ldap_default_group_dn, {"memberUid": [(MODIFY_ADD, [uid])]})
                    except LDAPAttributeOrValueExistsResult:
                        pass  # memberUid antigo no grupo: a conta já é membro
                    except LDAPException:
                        con.delete(dn)
                        raise
                    return uid_number
            except LDAPException as e:
                raise ErroDiretorio(str(e)) from e

    def definir_senha(self, uid: str, senha: str, hoje: date | None = None) -> None:
        """Troca a senha com o bind de serviço e confirma com um bind de teste."""
        try:
            with self._con() as con:
                dn = self._dn_de(con, uid)
                if dn is None:
                    raise ErroDiretorio(f"conta {uid} não encontrada")
                con.modify(dn, {
                    "userPassword": [(MODIFY_REPLACE, [contas.hash_ssha(senha)])],
                    "shadowLastChange": [(MODIFY_REPLACE, [str(contas.shadow_last_change(hoje))])],
                })
            with self._con(dn, senha):
                pass
        except LDAPException as e:
            raise ErroDiretorio(str(e)) from e
