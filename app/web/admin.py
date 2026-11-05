import functools
import logging
import re
from datetime import timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from .. import aprovacao, contas, convites, lote, tokens
from ..banco import iso
from ..diretorio import ErroDiretorio
from ..servicos import ip_cliente, svc

bp = Blueprint("admin", __name__, url_prefix="/admin")
log = logging.getLogger("ldap-self-signup")
SEM_CONFLITOS = {"uid": [], "cpf": [], "mail": []}
LOTE_TTL = timedelta(hours=1)  # validade da prévia do convite em lote
ACOES_ERRO = {"erro_ldap", "aprovacao_bloqueada", "falha_envio_link", "falha_envio_aviso", "falha_envio_convite"}
ROTULOS_ACAO = {
    "login": "Entrou no painel",
    "login_usuario": "Entrou na área do usuário",
    "solicitacao_criada": "Solicitação criada",
    "email_confirmado": "Confirmou o e-mail",
    "aprovar": "Aprovou",
    "rejeitar": "Rejeitou",
    "destravar": "Voltou a solicitação para pendente",
    "aprovacao_bloqueada": "Aprovação bloqueada",
    "erro_ldap": "Erro no LDAP",
    "link_enviado": "Enviou link de definir senha",
    "falha_envio_link": "Falha ao enviar o link de definir senha",
    "falha_envio_aviso": "Falha ao enviar o aviso",
    "falha_envio_convite": "Falha ao enviar o convite",
    "reset_senha": "Link de redefinição",
    "senha_definida": "Definiu a senha",
    "senha_alterada": "Trocou a senha",
    "alteracao_solicitada": "Pediu correção dos dados",
    "confirmacao_dados": "Pedido de confirmação dos dados",
    "dados_confirmados": "Confirmou os dados",
    "convite_criado": "Convite criado",
    "convite_enviado": "Convite enviado",
    "convite_aceito": "Convite aceito",
    "convite_alterado": "Convite aceito com alterações",
    "convite_preenchido": "Convite por e-mail preenchido",
    "convite_cancelado": "Convite cancelado",
    "lote_enviado": "Convites em lote enviados",
    "reset_lote": "Reset de senha em lote",
    "confirmacao_lote": "Confirmação de dados em lote",
}


def requer_admin(f):
    @functools.wraps(f)
    def envolvida(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("admin.login"))
        return f(*args, **kwargs)
    return envolvida


def _ldap_fora(e):
    log.error("erro no LDAP: %s", e)
    return render_template("erro_diretorio.html"), 503


@bp.route("/login", methods=["GET", "POST"])
def login():
    s = svc()
    erro = None
    if request.method == "POST":
        if not s.limite_login.permitir(ip_cliente()):
            return render_template("limite.html"), 429
        uid = request.form.get("uid", "").strip().lower()
        try:
            ok = s.diretorio.autenticar_admin(uid, request.form.get("senha", ""))
        except ErroDiretorio as e:
            return _ldap_fora(e)
        if ok:
            # sem session.clear() (preserva a sessão de usuário), mas com CSRF novo a cada login
            session.pop("csrf_token", None)
            session["admin"] = uid
            session.permanent = True
            s.banco.auditar(uid, "login", uid, "", s.agora())
            return redirect(url_for("admin.lista"))
        erro = "Usuário ou senha inválidos, ou sem permissão de administrador."
    return render_template("admin/login.html", erro=erro), (401 if erro else 200)


@bp.post("/sair")
def sair():
    session.pop("admin", None)
    return redirect(url_for("admin.login"))


STATUS = {"todos": "Todos", "pendente": "Pendente", "aprovando": "Em aprovação", "aprovada": "Aprovada",
          "rejeitada": "Rejeitada", "expirada": "Expirada", "aguardando_confirmacao": "Aguardando confirmação",
          "convidado": "Convidado"}
POR_PAGINA = 25


@bp.get("/")
@requer_admin
def lista():
    s = svc()
    s.banco.expirar_aguardando(s.agora() - timedelta(hours=s.cfg.token_ttl_hours))
    s.banco.limpar_lotes(s.agora() - LOTE_TTL)
    q = request.args.get("q", "").strip()[:200]
    status = request.args.get("status", "pendente")
    if status not in STATUS:
        status = "pendente"
    contagens = s.banco.contar_por_status(q)
    contagens["todos"] = sum(contagens.values())
    total = contagens.get(status, 0)
    paginas = max(-(-total // POR_PAGINA), 1)
    pagina = min(max(request.args.get("pagina", 1, type=int), 1), paginas)
    solicitacoes = s.banco.buscar(q, None if status == "todos" else status, pagina, POR_PAGINA)
    return render_template("admin/lista.html", solicitacoes=solicitacoes, total=total, q=q, status=status,
                           pagina=pagina, paginas=paginas, rotulos=STATUS, contagens=contagens)


def _carregar(sid: int) -> dict:
    sol = svc().banco.obter(sid)
    if sol is None:
        abort(404)
    return sol


def _conflitos(s, sol: dict) -> dict:
    """Conflitos no LDAP; numa alteração a própria conta não conta (nem o uid, que já existe por definição)."""
    c = s.diretorio.conflitos(sol["uid_sugerido"], sol["cpf"], sol["email"])
    if sol["origem"] != "alteracao":
        return c
    proprio = sol["uid_sugerido"]
    return {"uid": [], "cpf": [u for u in c["cpf"] if u != proprio], "mail": [u for u in c["mail"] if u != proprio]}


def _detalhe(sol: dict, erro: str | None = None, status: int = 200):
    s = svc()
    conflitos, orgs, atual = SEM_CONFLITOS, [], None
    try:
        if sol["status"] == "pendente":
            conflitos = _conflitos(s, sol)
            if sol["origem"] != "alteracao":
                orgs = s.diretorio.organizacoes()
        if sol["origem"] == "alteracao" and sol["status"] in ("pendente", "aprovando"):
            atual = s.diretorio.obter_conta(sol["uid_sugerido"])
    except ErroDiretorio as e:
        return _ldap_fora(e)
    alterados = contas.campos_alterados(atual, sol) if atual else []
    org_nova = sol["organizacao"] if sol["organizacao"] and sol["organizacao"] not in orgs else ""
    return render_template("admin/detalhe.html", sol=sol, org_nova=org_nova, conflitos=conflitos, orgs=orgs, atual=atual,
                           alterados=alterados,
                           consentimento=s.banco.consentimento(sol["id"]), historico=s.banco.historico(sol["id"]),
                           acoes_erro=ACOES_ERRO, rotulos=STATUS, erro=erro), status


@bp.get("/solicitacao/<int:sid>")
@requer_admin
def detalhe(sid):
    return _detalhe(_carregar(sid))


def _enviar_link(s, modelo: str, uid: str, email: str, nome: str, agora) -> bool:
    token = tokens.emitir(s.banco, tokens.DEFINIR_SENHA, uid, s.cfg.token_ttl_hours, agora)
    return s.enviar(modelo, email, nome=nome, uid=uid, link=s.link(f"/definir-senha/{token}"),
                    validade=s.cfg.token_ttl_hours, links=s.tema.dados.get("links", {}))


def _org_escolhida(orgs: list[str]) -> str:
    """Cliente do formulário: um da lista ou um novo (exige confirmação). Levanta contas.DadosInvalidos."""
    org = request.form.get("organizacao", "")
    if org == "__nova__" or org not in orgs:
        if request.form.get("confirmar_nova") != "sim":
            raise contas.DadosInvalidos("Confirme a criação do cliente novo.")
        if org == "__nova__":
            org = request.form.get("organizacao_nova", "")
    return contas.validar_org(org)


def _aprovar_alteracao(s, sol: dict, admin: str, bloquear, erro_ldap):
    sid, uid = sol["id"], sol["uid_sugerido"]
    try:
        if s.diretorio.obter_conta(uid) is None:
            return bloquear(f"A conta {uid} não existe mais no LDAP.", 409)
        conflitos = _conflitos(s, sol)
    except ErroDiretorio as e:
        return erro_ldap(e, f"alteração uid={uid}")
    if (conflitos["cpf"] or conflitos["mail"]) and request.form.get("confirmar_outra_pessoa") != "sim":
        return bloquear("Já existe outra conta com este CPF ou e-mail. Confirme que é outra pessoa.", 409)
    try:
        aprovacao.aplicar_alteracao(s, sid, ator=admin)
    except aprovacao.JaReivindicada:
        return bloquear("Esta solicitação não está pendente.", 409)
    except ErroDiretorio as e:
        return _ldap_fora(e)  # erro_ldap já registrado no histórico
    enviado = _enviar_link(s, "dados_atualizados", uid, sol["email"], sol["nome"], s.agora())
    s.banco.atualizar(sid, link_enviado=int(enviado))
    s.banco.auditar(admin, "link_enviado" if enviado else "falha_envio_link", f"sol:{sid}", sol["email"], s.agora())
    flash(f"Dados da conta {uid} atualizados." + (" Link enviado." if enviado else " Falha ao enviar o link: reenvie."))
    return redirect(url_for("admin.detalhe", sid=sid))


@bp.post("/solicitacao/<int:sid>/aprovar")
@requer_admin
def aprovar(sid):
    s, sol, admin = svc(), _carregar(sid), session["admin"]

    def bloquear(motivo: str, status: int):
        s.banco.auditar(admin, "aprovacao_bloqueada", f"sol:{sid}", motivo, s.agora())
        return _detalhe(_carregar(sid), motivo, status)

    def erro_ldap(e: ErroDiretorio, contexto: str):
        s.banco.auditar(admin, "erro_ldap", f"sol:{sid}", f"{contexto}: {e}", s.agora())
        return _ldap_fora(e)

    if sol["status"] != "pendente":
        return bloquear("Esta solicitação não está pendente.", 409)
    if sol["origem"] == "alteracao":
        return _aprovar_alteracao(s, sol, admin, bloquear, erro_ldap)
    try:
        orgs = s.diretorio.organizacoes()
    except ErroDiretorio as e:
        return erro_ldap(e, "ao listar clientes")
    try:
        org = _org_escolhida(orgs)
        uid = contas.validar_uid(request.form.get("uid", "").strip().lower())
    except contas.DadosInvalidos as e:
        return bloquear(str(e), 400)
    contexto = f"uid={uid} org={org}"
    try:
        conflitos = s.diretorio.conflitos(uid, sol["cpf"], sol["email"])
    except ErroDiretorio as e:
        return erro_ldap(e, contexto)
    if conflitos["uid"]:
        return bloquear(f"O usuário {uid} já existe. Escolha outro.", 409)
    if (conflitos["cpf"] or conflitos["mail"]) and request.form.get("confirmar_outra_pessoa") != "sim":
        return bloquear("Já existe conta com este CPF ou e-mail. Confirme que é outra pessoa.", 409)
    try:
        aprovacao.aprovar(s, sid, uid=uid, org=org, ator=admin)
    except aprovacao.JaReivindicada:
        return bloquear("Esta solicitação não está pendente.", 409)
    except ErroDiretorio as e:
        return _ldap_fora(e)  # erro_ldap já registrado no histórico
    agora = s.agora()
    enviado = _enviar_link(s, "conta_aprovada", uid, sol["email"], sol["nome"], agora)
    s.banco.atualizar(sid, link_enviado=int(enviado))
    s.banco.auditar(admin, "link_enviado" if enviado else "falha_envio_link", f"sol:{sid}", sol["email"], s.agora())
    flash(f"Conta {uid} criada." + (" Link enviado." if enviado else " Falha ao enviar o link: reenvie."))
    return redirect(url_for("admin.detalhe", sid=sid))


def _avisar_rejeicao(s, sol, motivo: str) -> bool:
    """Avisa a rejeição. Alteração vai ao e-mail atual do LDAP: o e-mail da solicitação é novo e não verificado."""
    if sol["origem"] != "alteracao":
        return s.enviar("solicitacao_rejeitada", sol["email"], nome=sol["nome"], motivo=motivo)
    try:
        conta = s.diretorio.obter_conta(sol["uid_sugerido"])
    except ErroDiretorio:
        return False
    if not conta or not conta.get("mail"):
        return False
    return s.enviar("alteracao_rejeitada", conta["mail"], nome=sol["nome"], motivo=motivo)


@bp.post("/solicitacao/<int:sid>/rejeitar")
@requer_admin
def rejeitar(sid):
    s, sol, admin = svc(), _carregar(sid), session["admin"]
    if sol["status"] != "pendente":
        return _detalhe(sol, "Esta solicitação não está pendente.", 409)
    motivo = request.form.get("motivo", "").strip()[:500]
    agora = s.agora()
    if not s.banco.rejeitar(sid, motivo, admin, iso(agora)):
        return _detalhe(_carregar(sid), "Esta solicitação não está pendente.", 409)
    aviso_falhou = request.form.get("avisar") == "sim" and not _avisar_rejeicao(s, sol, motivo)
    s.banco.auditar(admin, "rejeitar", f"sol:{sid}", motivo, agora)
    if aviso_falhou:
        s.banco.auditar(admin, "falha_envio_aviso", f"sol:{sid}", sol["email"], agora)
    flash("Solicitação rejeitada (falha ao enviar o aviso por e-mail)." if aviso_falhou
          else "Solicitação rejeitada.")
    return redirect(url_for("admin.lista"))


@bp.post("/solicitacao/<int:sid>/destravar")
@requer_admin
def destravar(sid):
    s, sol = svc(), _carregar(sid)
    if not s.banco.destravar(sid):
        return _detalhe(sol, "Esta solicitação não está em aprovação.", 409)
    s.banco.auditar(session["admin"], "destravar", f"sol:{sid}", "", s.agora())
    flash("Solicitação voltou para pendente.")
    return redirect(url_for("admin.detalhe", sid=sid))


@bp.post("/solicitacao/<int:sid>/reenviar")
@requer_admin
def reenviar(sid):
    s, sol = svc(), _carregar(sid)
    if sol["status"] != "aprovada":
        abort(409)
    agora = s.agora()
    modelo = "dados_atualizados" if sol["origem"] == "alteracao" else "conta_aprovada"
    enviado = _enviar_link(s, modelo, sol["uid_final"], sol["email"], sol["nome"], agora)
    s.banco.atualizar(sid, link_enviado=int(enviado))
    s.banco.auditar(session["admin"], "link_enviado" if enviado else "falha_envio_link", f"sol:{sid}",
                    sol["email"], agora)
    flash("Link reenviado." if enviado else "Falha ao enviar o e-mail. Tente de novo.")
    return redirect(url_for("admin.detalhe", sid=sid))


SEM_CLIENTE = "__sem__"


def _normal(texto: str) -> str:
    return contas.sem_acento(texto).casefold()


def _filtrar_contas(todas: list[dict], q: str) -> list[dict]:
    """Contas com o trecho em uid, nome, e-mail, cliente ou CPF (sem diferenciar maiúsculas e acentos)."""
    termo = _normal(q)
    digitos = re.sub(r"\D", "", q) if re.fullmatch(r"[\d.\-/ ]+", q) else ""
    return [c for c in todas
            if any(termo in _normal(c[k]) for k in ("uid", "cn", "mail", "ou")) or (digitos and digitos in c["cpf"])]


def _do_cliente(achadas: list[dict], cliente: str) -> list[dict]:
    if cliente == SEM_CLIENTE:
        return [c for c in achadas if not c["ou"]]
    return [c for c in achadas if c["ou"] == cliente] if cliente else achadas


def _cliente_valido(todas: list[dict], cliente: str) -> str:
    return cliente if cliente == SEM_CLIENTE or cliente in {c["ou"] for c in todas if c["ou"]} else ""


@bp.get("/contas")
@requer_admin
def contas_busca():
    s = svc()
    q = request.args.get("q", "").strip()[:200]
    try:
        todas = s.diretorio.listar_contas()
    except ErroDiretorio as e:
        return _ldap_fora(e)
    cliente = _cliente_valido(todas, request.args.get("cliente", ""))
    achadas = _filtrar_contas(todas, q)
    clientes = sorted({c["ou"] for c in todas if c["ou"]}, key=str.lower)
    contagens = {o: sum(c["ou"] == o for c in achadas) for o in clientes}
    contagens[""] = len(achadas)
    contagens[SEM_CLIENTE] = sum(not c["ou"] for c in achadas)
    filtradas = _do_cliente(achadas, cliente)
    total = len(filtradas)
    paginas = max(-(-total // POR_PAGINA), 1)
    pagina = min(max(request.args.get("pagina", 1, type=int), 1), paginas)
    inicio = (pagina - 1) * POR_PAGINA
    return render_template("admin/contas.html", q=q, cliente=cliente, contas=filtradas[inicio:inicio + POR_PAGINA],
                           total=total, pagina=pagina, paginas=paginas, clientes=clientes, contagens=contagens,
                           sem_cliente=SEM_CLIENTE)


@bp.get("/contas/<uid>")
@requer_admin
def conta(uid):
    s = svc()
    try:
        dados = s.diretorio.obter_conta(uid)
        grupos = s.diretorio.grupos_de(uid) if dados else []
    except ErroDiretorio as e:
        return _ldap_fora(e)
    if dados is None:
        abort(404)
    solicitacoes = s.banco.solicitacoes_da_conta(uid)
    historico = s.banco.historico_da_conta(uid, [x["id"] for x in solicitacoes])
    return render_template("admin/conta.html", conta=dados, grupos=grupos, solicitacoes=solicitacoes,
                           historico=historico, acoes_erro=ACOES_ERRO, rotulos=STATUS)


def _enviar_reset(s, conta: dict, admin: str) -> bool:
    """Emite o token de definir senha, envia o e-mail reset_senha e audita (individual e em lote)."""
    agora = s.agora()
    enviado = _enviar_link(s, "reset_senha", conta["uid"], conta["mail"], conta["cn"], agora)
    s.banco.auditar(admin, "reset_senha", conta["uid"], "ok" if enviado else "falha_envio", agora)
    return enviado


@bp.post("/contas/<uid>/reset")
@requer_admin
def reset(uid):
    s = svc()
    try:
        conta = s.diretorio.obter_conta(uid)
    except ErroDiretorio as e:
        return _ldap_fora(e)
    if conta is None:
        abort(404)
    if not conta["mail"]:
        flash(f"A conta {uid} não tem e-mail: cadastre o e-mail antes.")
        return redirect(url_for("admin.contas_busca", q=uid))
    enviado = _enviar_reset(s, conta, session["admin"])
    flash(f"Link de redefinição enviado para {contas.mascarar_email(conta['mail'])}." if enviado
          else "Falha ao enviar o e-mail. Tente de novo.")
    return redirect(url_for("admin.contas_busca", q=uid))


def _enviar_confirmacao(s, conta: dict, admin: str) -> bool:
    """Emite o token confirmar_dados, envia o e-mail confirmar_dados e audita (individual e em lote)."""
    agora = s.agora()
    token = tokens.emitir(s.banco, tokens.CONFIRMAR_DADOS, conta["uid"], s.cfg.token_ttl_hours, agora)
    enviado = s.enviar("confirmar_dados", conta["mail"], nome=conta["cn"], uid=conta["uid"],
                       link=s.link(f"/confirmar-dados/{token}"), validade=s.cfg.token_ttl_hours)
    s.banco.auditar(admin, "confirmacao_dados", conta["uid"], "ok" if enviado else "falha_envio", agora)
    return enviado


@bp.post("/contas/<uid>/confirmacao")
@requer_admin
def confirmacao(uid):
    s = svc()
    try:
        conta = s.diretorio.obter_conta(uid)
    except ErroDiretorio as e:
        return _ldap_fora(e)
    if conta is None:
        abort(404)
    if not conta["mail"]:
        flash(f"A conta {uid} não tem e-mail: cadastre o e-mail antes.")
        return redirect(url_for("admin.contas_busca", q=uid))
    enviado = _enviar_confirmacao(s, conta, session["admin"])
    flash(f"Pedido de confirmação dos dados enviado para {contas.mascarar_email(conta['mail'])}." if enviado
          else "Falha ao enviar o e-mail. Tente de novo.")
    return redirect(url_for("admin.contas_busca", q=uid))


LIMITE_LOTE = 200


def _alvo_do_lote(todas: list[dict]) -> dict:
    """Contas do lote de contas, recalculadas no servidor a partir do formulário (uids ou filtro atual)."""
    if request.form.get("todos_do_filtro") == "sim":
        q = request.form.get("q", "").strip()[:200]
        cliente = _cliente_valido(todas, request.form.get("cliente", ""))
        achadas, nao_encontradas = _do_cliente(_filtrar_contas(todas, q), cliente), []
        filtro = {"todos_do_filtro": "sim", "q": q, "cliente": cliente}
    else:
        uids = []
        for uid in request.form.getlist("uid"):
            try:
                uid = contas.validar_uid(uid)
            except contas.DadosInvalidos:
                continue
            if uid not in uids:
                uids.append(uid)
        por_uid = {c["uid"]: c for c in todas}
        achadas = [por_uid[u] for u in uids if u in por_uid]
        nao_encontradas = [u for u in uids if u not in por_uid]
        filtro = {"uids": uids}
    return {"com_email": [c for c in achadas if c["mail"]], "sem_email": [c for c in achadas if not c["mail"]],
            "nao_encontradas": nao_encontradas, "total": len(achadas) + len(nao_encontradas), "filtro": filtro}


def _erro_do_lote(alvo: dict) -> str | None:
    if not alvo["total"]:
        return "Selecione ao menos uma conta."
    if alvo["total"] > LIMITE_LOTE:
        return (f"A seleção tem {alvo['total']} contas; o limite é {LIMITE_LOTE} por envio: "
                "filtre por cliente ou busca e envie em partes.")
    return None


ACOES_LOTE = {
    "reset": {"titulo": "Reset de senha em lote", "envio": "admin.reset_lote", "auditoria": "reset_lote",
              "um": "conta receberá o link de redefinição de senha",
              "varias": "contas receberão o link de redefinição de senha",
              "nota": "o link anterior de cada conta deixa de valer"},
    "confirmacao": {"titulo": "Confirmação de dados em lote", "envio": "admin.confirmacao_lote",
                    "auditoria": "confirmacao_lote",
                    "um": "conta receberá o pedido de confirmação dos dados",
                    "varias": "contas receberão o pedido de confirmação dos dados",
                    "nota": "o pedido anterior de cada conta deixa de valer"},
}


def _preparar_lote(acao: dict):
    """(alvo, None) ou (None, resposta de erro) para as rotas de lote de contas."""
    try:
        alvo = _alvo_do_lote(svc().diretorio.listar_contas())
    except ErroDiretorio as e:
        return None, _ldap_fora(e)
    erro = _erro_do_lote(alvo)
    if erro:
        return None, (render_template("admin/reset_lote_confirmar.html", alvo=alvo, acao=acao, erro=erro), 400)
    return alvo, None


def _confirmar_lote(acao: dict):
    alvo, erro = _preparar_lote(acao)
    return erro or render_template("admin/reset_lote_confirmar.html", alvo=alvo, acao=acao, erro=None)


def _executar_lote(acao: dict, enviar):
    s, admin = svc(), session["admin"]
    alvo, erro = _preparar_lote(acao)
    if erro:
        return erro
    resultados = [{**c, "enviado": enviar(s, c, admin)} for c in alvo["com_email"]]
    contagem = {"enviados": sum(r["enviado"] for r in resultados),
                "falhas": sum(not r["enviado"] for r in resultados),
                "sem_email": len(alvo["sem_email"]), "nao_encontradas": len(alvo["nao_encontradas"])}
    s.banco.auditar(admin, acao["auditoria"], "contas", " ".join(f"{k}={v}" for k, v in contagem.items()),
                    s.agora())
    return render_template("admin/reset_lote_resultado.html", alvo=alvo, acao=acao, resultados=resultados,
                           contagem=contagem)


@bp.post("/contas/reset-lote/confirmar")
@requer_admin
def reset_lote_confirmar():
    return _confirmar_lote(ACOES_LOTE["reset"])


@bp.post("/contas/reset-lote")
@requer_admin
def reset_lote():
    return _executar_lote(ACOES_LOTE["reset"], _enviar_reset)


@bp.post("/contas/confirmacao-lote/confirmar")
@requer_admin
def confirmacao_lote_confirmar():
    return _confirmar_lote(ACOES_LOTE["confirmacao"])


@bp.post("/contas/confirmacao-lote")
@requer_admin
def confirmacao_lote():
    return _executar_lote(ACOES_LOTE["confirmacao"], _enviar_confirmacao)


CAMPOS_CONVITE = ("nome", "cpf", "email", "telefone", "uid", "organizacao", "organizacao_nova")


@bp.route("/convidar", methods=["GET", "POST"])
@requer_admin
def convidar():
    s, admin = svc(), session["admin"]
    try:
        orgs = s.diretorio.organizacoes()
    except ErroDiretorio as e:
        return _ldap_fora(e)
    form = {c: request.form.get(c, "") for c in CAMPOS_CONVITE}

    def pagina(erros: dict, status: int, conflitos=SEM_CONFLITOS):
        return render_template("admin/convidar.html", form=form, erros=erros, orgs=orgs,
                               conflitos=conflitos), status

    if request.method == "GET":
        return pagina({}, 200)
    dados, erros = contas.validar_formulario(form, justificativa_opcional=True)
    uid = form["uid"].strip().lower()
    try:
        if not uid and "nome" in dados:
            uid = contas.derivar_nomes(dados["nome"])["uid"]
        uid = contas.validar_uid(uid) if uid else ""
    except contas.DadosInvalidos as e:
        erros["uid"] = str(e)
    try:
        org = _org_escolhida(orgs)
    except contas.DadosInvalidos as e:
        erros["organizacao"] = str(e)
    if erros:
        return pagina(erros, 400)
    try:
        conflitos = s.diretorio.conflitos(uid, dados["cpf"], dados["email"])
    except ErroDiretorio as e:
        return _ldap_fora(e)
    if conflitos["uid"]:
        return pagina({"uid": f"O usuário {uid} já existe. Escolha outro."}, 409, conflitos)
    reservado = s.banco.convite_aberto_com_uid(uid, exceto_cpf=dados["cpf"])
    if reservado is not None:
        return pagina({"uid": f"O usuário {uid} já está reservado pelo convite #{reservado}. Escolha outro."}, 409)
    if (conflitos["cpf"] or conflitos["mail"]) and request.form.get("confirmar_outra_pessoa") != "sim":
        return pagina({"geral": "Já existe conta com este CPF ou e-mail. Confirme que é outra pessoa."}, 409,
                      conflitos)
    sid, enviado = convites.criar(s, dados, uid=uid, org=org, admin=admin)
    flash(f"Convite enviado para {dados['email']}." if enviado
          else "Convite criado, mas o e-mail não foi enviado: reenvie.")
    return redirect(url_for("admin.detalhe", sid=sid))


def _previa_emails(s, textos: list[str]) -> list[dict]:
    """Uma linha por e-mail (ordem de entrada, sem repetir): motivo é None quando enviável."""
    linhas, vistos = [], set()
    for texto in textos:
        try:
            email = contas.validar_email(texto)
        except contas.DadosInvalidos as e:
            if texto not in vistos:
                vistos.add(texto)
                linhas.append({"email": texto, "motivo": str(e), "substitui": None})
            continue
        if email in vistos:
            continue
        vistos.add(email)
        existentes = s.diretorio.contas_por_email(email)
        if existentes:
            motivo = (f"Já tem conta (usuário {', '.join(c['uid'] for c in existentes)}): "
                      "use Esqueci minha senha ou o reset.")
            linhas.append({"email": email, "motivo": motivo, "substitui": None})
        else:
            linhas.append({"email": email, "motivo": None, "substitui": s.banco.convite_email_aberto(email)})
    return linhas


def _contagem(resultados: list[dict]) -> dict:
    return {r: sum(1 for x in resultados if x["resultado"] == r) for r in ("enviado", "falha de envio", "pulado")}


@bp.route("/convidar-por-email", methods=["GET", "POST"])
@requer_admin
def convidar_por_email():
    s, admin = svc(), session["admin"]
    try:
        orgs = s.diretorio.organizacoes()
    except ErroDiretorio as e:
        return _ldap_fora(e)
    form = {c: request.form.get(c, "") for c in ("emails", "organizacao", "organizacao_nova", "confirmar_nova")}

    def pagina(status=200, erro=None, linhas=None):
        return render_template("admin/convidar_email.html", form=form, orgs=orgs, erro=erro, linhas=linhas,
                               resultados=None, cliente="", contagem=None), status

    if request.method == "GET":
        return pagina()
    acao = request.form.get("acao")
    if acao == "voltar":
        return pagina()
    if acao == "previa":
        textos = [e for e in re.split(r"[\s,;]+", form["emails"]) if e]
    elif acao == "enviar":
        textos = [e for e in request.form.getlist("email") if e.strip()]
    else:
        abort(400)
    if not textos:
        return pagina(400, "Informe ao menos um e-mail.")
    try:
        org = _org_escolhida(orgs)
        linhas = _previa_emails(s, textos)
    except contas.DadosInvalidos as e:
        return pagina(400, str(e))
    except ErroDiretorio as e:
        return _ldap_fora(e)
    enviaveis = [linha for linha in linhas if linha["motivo"] is None]
    if len(enviaveis) > LIMITE_LOTE:
        return pagina(400, f"São {len(enviaveis)} e-mails; o limite é {LIMITE_LOTE} por envio: é preciso dividir a lista.",
                      linhas)
    if acao == "previa":
        return pagina(200, None, linhas)
    resultados = []
    for linha in linhas:
        if linha["motivo"] is not None:
            resultados.append({**linha, "resultado": "pulado", "sid": None, "cliente": org})
            continue
        sid, enviado = convites.criar_por_email(s, linha["email"], org=org, admin=admin)
        resultados.append({**linha, "resultado": "enviado" if enviado else "falha de envio", "sid": sid,
                           "cliente": org})
    # POST/redirect/get: o resultado fica numa linha de `lotes`; recarregar a página só o lê de novo
    rid = s.banco.criar_lote(admin, resultados, s.agora(), expira_antes=s.agora() - LOTE_TTL)
    return redirect(url_for("admin.convidar_por_email_resultado", rid=rid))


@bp.get("/convidar-por-email/resultado/<int:rid>")
@requer_admin
def convidar_por_email_resultado(rid):
    s = svc()
    resultados = s.banco.obter_lote(rid, session["admin"], s.agora() - LOTE_TTL)
    if not resultados:
        return render_template("admin/lote.html", erro="Este resultado expirou."), 410
    form = dict.fromkeys(("emails", "organizacao", "organizacao_nova", "confirmar_nova"), "")
    return render_template("admin/convidar_email.html", form=form, orgs=[], erro=None, linhas=None,
                           resultados=resultados, cliente=resultados[0]["cliente"],
                           contagem=_contagem(resultados))


@bp.post("/solicitacao/<int:sid>/reenviar-convite")
@requer_admin
def reenviar_convite(sid):
    s, sol = svc(), _carregar(sid)
    if sol["status"] != "convidado":
        abort(409)
    enviado = convites.enviar(s, sid, session["admin"])
    flash("Convite reenviado." if enviado else "Falha ao enviar o e-mail. Tente de novo.")
    return redirect(url_for("admin.detalhe", sid=sid))


@bp.post("/solicitacao/<int:sid>/cancelar-convite")
@requer_admin
def cancelar_convite(sid):
    s = svc()
    _carregar(sid)
    agora = s.agora()
    if not s.banco.cancelar_convite(sid, agora):
        abort(409)
    s.banco.auditar(session["admin"], "convite_cancelado", f"sol:{sid}", "", agora)
    flash("Convite cancelado.")
    return redirect(url_for("admin.detalhe", sid=sid))


MSG_LOTE_EXPIRADO = "Esta prévia expirou ou já foi enviada. Envie a planilha de novo."


@bp.route("/convidar/lote", methods=["GET", "POST"])
@requer_admin
def lote_upload():
    s = svc()
    if request.method == "GET":
        return render_template("admin/lote.html")
    arquivo = request.files.get("planilha")
    if arquivo is None or not arquivo.filename:
        return render_template("admin/lote.html", erro="Escolha a planilha."), 400
    try:
        linhas = lote.ler_planilha(arquivo.filename, arquivo.read(lote.MAX_BYTES + 1))
    except lote.PlanilhaInvalida as e:
        return render_template("admin/lote.html", erro=str(e)), 400
    lid = s.banco.criar_lote(session["admin"], linhas, s.agora(), expira_antes=s.agora() - LOTE_TTL)
    return redirect(url_for("admin.lote_previa", lid=lid))


def _bloqueio_do_lote(item: dict) -> str | None:
    """Motivo para não convidar a linha marcada (revalidada no servidor), ou None."""
    if item["erros"]:
        return " ".join(item["erros"].values())
    if item["erro_uid"]:
        return item["erro_uid"]
    if item["existe"] and request.form.get(f"outra_pessoa_{item['i']}") != "sim":
        return "Já existe conta com este CPF ou e-mail. Confirme que é outra pessoa."
    return None


@bp.route("/convidar/lote/<int:lid>", methods=["GET", "POST"])
@requer_admin
def lote_previa(lid):
    s, admin = svc(), session["admin"]
    linhas = s.banco.obter_lote(lid, admin, s.agora() - LOTE_TTL)
    if linhas is None:
        return render_template("admin/lote.html", erro=MSG_LOTE_EXPIRADO), 410
    post = request.method == "POST"
    uids = {i: request.form.get(f"uid_{i}", "") for i in range(len(linhas))} if post else {}
    marcadas = {i for i in range(len(linhas)) if request.form.get(f"enviar_{i}") == "sim"}
    try:
        orgs = s.diretorio.organizacoes()
        itens = lote.previa(s, linhas, uids)
    except ErroDiretorio as e:
        return _ldap_fora(e)

    def pagina(erro: str | None = None, status: int = 200):
        return render_template("admin/lote_previa.html", lid=lid, itens=itens, orgs=orgs, form=request.form,
                               marcadas=marcadas if post else None, erro=erro), status

    if not post:
        return pagina()
    try:
        org = _org_escolhida(orgs)
    except contas.DadosInvalidos as e:
        return pagina(str(e), 400)
    if not marcadas:
        return pagina("Marque ao menos uma linha.", 400)
    try:
        itens = lote.previa(s, linhas, uids, so=marcadas)
    except ErroDiretorio as e:
        return _ldap_fora(e)
    if not s.banco.remover_lote(lid):  # outro envio do mesmo lote chegou antes
        return render_template("admin/lote.html", erro=MSG_LOTE_EXPIRADO), 410
    resultados = []
    for item in itens:
        motivo = _bloqueio_do_lote(item)
        if motivo:
            resultados.append({**item, "resultado": "bloqueado", "motivo": motivo})
            continue
        sid, enviado = convites.criar(s, item["dados"], uid=item["uid"], org=org, admin=admin)
        resultados.append({**item, "sid": sid, "resultado": "enviado" if enviado else "falha de envio"})
    contagem = {r: sum(x["resultado"] == r for x in resultados) for r in ("enviado", "falha de envio", "bloqueado")}
    s.banco.auditar(admin, "lote_enviado", f"lote:{lid}", f"enviados={contagem['enviado']} "
                    f"falhas={contagem['falha de envio']} bloqueados={contagem['bloqueado']}", s.agora())
    return render_template("admin/lote_resultado.html", resultados=resultados, contagem=contagem, org=org)
