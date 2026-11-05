"""Convites: o admin inicia o cadastro e a pessoa recebe o link para conferir os dados (spec §17)."""
from . import tokens


def criar(s, dados: dict, *, uid: str, org: str, admin: str) -> tuple[int, bool]:
    """Cria o convite (substituindo o convite em aberto do mesmo CPF) e envia o link. Retorna (sid, enviado)."""
    agora = s.agora()
    anteriores = s.banco.expirar_convites_do_cpf(dados["cpf"], agora)
    sid = s.banco.criar_convite(dados, uid=uid, organizacao=org, convidado_por=admin, agora=agora)
    for anterior in anteriores:
        s.banco.auditar(admin, "convite_cancelado", f"sol:{anterior}", f"substituído pelo convite #{sid}", agora)
    s.banco.auditar(admin, "convite_criado", f"sol:{sid}", f"uid={uid} org={org}", agora)
    return sid, enviar(s, sid, admin)


def criar_por_email(s, email: str, *, org: str, admin: str) -> tuple[int, bool]:
    """Convite só com o e-mail (spec §23): a pessoa preenche o resto. Substitui o convite em aberto do mesmo e-mail."""
    agora = s.agora()
    anteriores = s.banco.expirar_convites_do_email(email, agora)
    sid = s.banco.criar_convite_email(email, organizacao=org, convidado_por=admin, agora=agora)
    for anterior in anteriores:
        s.banco.auditar(admin, "convite_cancelado", f"sol:{anterior}", f"substituído pelo convite #{sid}", agora)
    s.banco.auditar(admin, "convite_criado", f"sol:{sid}", f"email={email} org={org}", agora)
    return sid, enviar(s, sid, admin)


def enviar(s, sid: int, admin: str) -> bool:
    """Emite um link novo (invalida o anterior), envia o e-mail e registra o resultado."""
    sol, agora = s.banco.obter(sid), s.agora()
    token = tokens.emitir(s.banco, tokens.CONVITE, f"sol:{sid}", s.cfg.convite_ttl_dias * 24, agora)
    if sol["origem"] == "convite_email":
        enviado = s.enviar("convite_email", sol["email"], link=s.link(f"/convite/{token}"),
                           validade_dias=s.cfg.convite_ttl_dias, convidado_por=sol["convidado_por"])
    else:
        enviado = s.enviar("convite", sol["email"], nome=sol["nome"], link=s.link(f"/convite/{token}"),
                           validade_dias=s.cfg.convite_ttl_dias, convidado_por=sol["convidado_por"])
    s.banco.atualizar(sid, link_enviado=int(enviado))
    s.banco.auditar(admin, "convite_enviado" if enviado else "falha_envio_convite", f"sol:{sid}", sol["email"],
                    agora)
    return enviado
