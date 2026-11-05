"""Decisão de uma solicitação: criação da conta (aprovação no painel e aceite de convite) e alteração de dados."""
from .banco import iso
from .diretorio import ErroDiretorio


class JaReivindicada(Exception):
    """A solicitação não está mais no status esperado (outra aprovação ou aceite chegou antes)."""


def aprovar(s, sid: int, *, uid: str, org: str, ator: str) -> int:
    """Reivindica a solicitação (pendente -> aprovando), cria a conta e registra. Retorna o uidNumber."""
    if not s.banco.reivindicar(sid):
        raise JaReivindicada()
    return criar_conta(s, sid, volta_para="pendente", uid=uid, org=org, ator=ator)


def criar_conta(s, sid: int, *, volta_para: str, uid: str, org: str, ator: str) -> int:
    """Cria a conta de uma solicitação já reivindicada (status aprovando) e registra. Retorna o uidNumber.

    Erro de LDAP: devolve a solicitação para `volta_para`, registra erro_ldap no histórico e propaga.
    """
    sol = s.banco.obter(sid)
    contexto = f"uid={uid} org={org}"
    try:
        uid_number = s.diretorio.criar_conta(uid=uid, nome=sol["nome"], cpf=sol["cpf"], mail=sol["email"],
                                             telefone=sol["telefone"], org=org)
    except ErroDiretorio as e:
        s.banco.atualizar(sid, status=volta_para)
        s.banco.auditar(ator, "erro_ldap", f"sol:{sid}", f"{contexto}: {e}", s.agora())
        raise
    agora = s.agora()
    s.banco.atualizar(sid, status="aprovada", uid_final=uid, organizacao=org, decidido_por=ator,
                      decidido_em=iso(agora))
    s.banco.auditar(ator, "aprovar", f"sol:{sid}", f"{contexto} uidNumber={uid_number}", agora)
    return uid_number


def aplicar_alteracao(s, sid: int, *, ator: str) -> None:
    """Reivindica a alteração (pendente -> aprovando), atualiza a conta existente no LDAP e registra.

    Erro de LDAP: devolve a solicitação para pendente, registra erro_ldap no histórico e propaga.
    """
    if not s.banco.reivindicar(sid):
        raise JaReivindicada()
    sol = s.banco.obter(sid)
    uid = sol["uid_sugerido"]
    try:
        s.diretorio.atualizar_dados(uid, nome=sol["nome"], cpf=sol["cpf"], mail=sol["email"],
                                    telefone=sol["telefone"])
    except ErroDiretorio as e:
        s.banco.atualizar(sid, status="pendente")
        s.banco.auditar(ator, "erro_ldap", f"sol:{sid}", f"alteração uid={uid}: {e}", s.agora())
        raise
    agora = s.agora()
    s.banco.atualizar(sid, status="aprovada", uid_final=uid, decidido_por=ator, decidido_em=iso(agora))
    s.banco.auditar(ator, "aprovar", f"sol:{sid}", f"alteração uid={uid}", agora)
