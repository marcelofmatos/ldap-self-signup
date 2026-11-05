import logging
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .. import aprovacao, contas, tokens
from ..banco import iso
from ..diretorio import ErroDiretorio
from ..formatos import cpf, telefone
from ..servicos import ip_cliente, svc

bp = Blueprint("publico", __name__)
log = logging.getLogger("ldap-self-signup")

CAMPOS = ("nome", "cpf", "email", "telefone", "justificativa")
MSG_CONSENTIMENTO = "Para continuar, marque que você leu e concorda com o aviso de privacidade."


def _serializador() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(svc().cfg.secret_key, salt="revisao")


def _revisao(dados, pacote, erro=None, status=200):
    return render_template("revisao.html", dados=dados, pacote=pacote,
                           privacidade=svc().tema.privacidade_html, erro=erro), status


@bp.get("/")
def inicio():
    return render_template("inicio.html", logado=bool(session.get("usuario")))


@bp.get("/cadastro")
def formulario():
    return render_template("formulario.html", form={}, erros={})


MSG_ESQUECI = "Se o e-mail estiver cadastrado, enviamos um link para definir uma nova senha."


INTERVALO_ESQUECI = timedelta(minutes=15)


def _enviar_esqueci_senha(s, conta: dict) -> None:
    """Fora da requisição (o tempo de resposta não revela se o e-mail existe). Não usa contexto Flask."""
    try:
        agora = s.agora()
        uid = conta["uid"]
        if s.banco.esqueci_senha_recente(uid, agora - INTERVALO_ESQUECI):
            s.banco.auditar("publico", "reset_senha", uid, "esqueci_senha · ignorado (intervalo)", agora)
            return
        token = tokens.emitir(s.banco, tokens.DEFINIR_SENHA, uid, s.cfg.token_ttl_hours, agora,
                              invalidar_anteriores=False)
        enviado = s.enviar("reset_senha", conta["mail"], nome=conta["cn"], uid=uid,
                           link=s.link(f"/definir-senha/{token}"), validade=s.cfg.token_ttl_hours,
                           links=s.tema.dados.get("links", {}))
        s.banco.auditar("publico", "reset_senha", uid,
                        "esqueci_senha" if enviado else "esqueci_senha · falha_envio", agora)
    except Exception:
        log.exception("falha ao processar esqueci-senha")


@bp.get("/esqueci-senha")
def esqueci_senha_form():
    return render_template("esqueci_senha.html", email="", erro=None, enviado=False)


@bp.post("/esqueci-senha")
def esqueci_senha():
    s = svc()
    if not s.limite_form.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    bruto = request.form.get("email", "")
    try:
        email = contas.validar_email(bruto)
    except contas.DadosInvalidos as e:
        return render_template("esqueci_senha.html", email=bruto, erro=str(e), enviado=False), 400
    try:
        achadas = s.diretorio.contas_por_email(email)
    except ErroDiretorio as e:
        log.error("falha no LDAP ao buscar e-mail para redefinir senha: %s", e)
        return render_template("erro_diretorio.html"), 503
    for conta in achadas:
        s.em_segundo_plano(lambda conta=conta: _enviar_esqueci_senha(s, conta))
    return render_template("esqueci_senha.html", email="", erro=None, enviado=True)


@bp.get("/privacidade")
def privacidade():
    return render_template("privacidade.html", privacidade=svc().tema.privacidade_html)


@bp.post("/cadastro")
def revisar():
    s = svc()
    if request.form.get("site"):
        return render_template("enviado.html")
    if not s.limite_form.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    form = {c: request.form.get(c, "") for c in CAMPOS}
    dados, erros = contas.validar_formulario(form)
    if erros:
        return render_template("formulario.html", form=form, erros=erros), 400
    return _revisao(dados, _serializador().dumps(dados))


@bp.post("/confirmar")
def confirmar():
    s = svc()
    if not (s.limite_form.permitir(ip_cliente()) and s.limite_token.permitir(ip_cliente())):
        return render_template("limite.html"), 429
    pacote = request.form.get("pacote", "")
    try:
        dados = _serializador().loads(pacote, max_age=3600)
    except BadSignature:
        return render_template("formulario.html", form={},
                               erros={"geral": "A revisão expirou. Preencha novamente."}), 400
    if request.form.get("consentimento") != "sim":
        return _revisao(dados, pacote, MSG_CONSENTIMENTO, 400)
    agora = s.agora()
    sid = s.banco.criar_solicitacao(
        dados, uid_sugerido=contas.derivar_nomes(dados["nome"])["uid"], ip=ip_cliente(),
        user_agent=request.headers.get("User-Agent", "")[:300],
        versao_aviso=s.tema.privacidade_versao, texto_aviso=s.tema.privacidade_texto, agora=agora)
    token = tokens.emitir(s.banco, tokens.CONFIRMAR_EMAIL, f"sol:{sid}", s.cfg.token_ttl_hours, agora)
    if not s.enviar("confirmar_email", dados["email"], nome=dados["nome"],
                    link=s.link(f"/confirmar-email/{token}"), validade=s.cfg.token_ttl_hours):
        s.banco.remover_solicitacao(sid)
        return render_template("erro_envio.html"), 503
    s.banco.auditar("publico", "solicitacao_criada", f"sol:{sid}", "", agora)
    return render_template("enviado.html")


@bp.get("/confirmar-email/<token>")
def confirmar_email_form(token):
    s = svc()
    if tokens.validar(s.banco, token, tokens.CONFIRMAR_EMAIL, s.agora()) is None:
        return render_template("link_invalido.html"), 410
    return render_template("confirmar_email.html")


@bp.post("/confirmar-email/<token>")
def confirmar_email(token):
    s = svc()
    if not s.limite_token.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    agora = s.agora()
    alvo = tokens.consumir(s.banco, token, tokens.CONFIRMAR_EMAIL, agora)
    if alvo is None:
        return render_template("link_invalido.html"), 410
    sid = int(alvo.removeprefix("sol:"))
    if not s.banco.confirmar_email(sid, agora):
        return render_template("link_invalido.html"), 410
    sol = s.banco.obter(sid)
    if sol["origem"] != "alteracao":
        s.banco.expirar_anteriores(sol["cpf"], sol["email"], sid)
    s.banco.auditar("publico", "email_confirmado", f"sol:{sid}", "", agora)
    s.enviar("nova_solicitacao", s.cfg.admin_notify_email, nome=sol["nome"], email=sol["email"],
             link=s.link(f"/admin/solicitacao/{sid}"),
             **({"alteracao": True} if sol["origem"] == "alteracao" else {}))
    return render_template("email_confirmado.html")


def _email_da_conta_do_link(token: str) -> tuple[str, dict] | None:
    """(uid, pendente) do link definir_email válido, se a conta ainda tem um e-mail pendente."""
    s = svc()
    uid = tokens.validar(s.banco, token, tokens.DEFINIR_EMAIL, s.agora())
    pendente = s.banco.email_pendente(uid) if uid else None
    return (uid, pendente) if pendente else None


@bp.get("/confirmar-email-conta/<token>")
def confirmar_email_conta_form(token):
    achado = _email_da_conta_do_link(token)
    if achado is None:
        return render_template("link_invalido.html"), 410
    uid, pendente = achado
    return render_template("confirmar_email_conta.html", uid=uid, email=pendente["email"])


@bp.post("/confirmar-email-conta/<token>")
def confirmar_email_conta(token):
    s = svc()
    if not s.limite_token.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    agora = s.agora()
    achado = _email_da_conta_do_link(token)
    if achado is None:
        return render_template("link_invalido.html"), 410
    uid, pendente = achado
    email = pendente["email"]
    try:
        if s.diretorio.obter_conta(uid) is None:
            return render_template("link_invalido.html"), 410
        if any(c["uid"] != uid for c in s.diretorio.contas_por_email(email)):
            return render_template("link_invalido.html", motivo="Este e-mail já é usado por outra conta."), 409
        s.diretorio.definir_email(uid, email)
    except ErroDiretorio as e:
        log.error("falha ao definir e-mail de %s: %s", uid, e)
        return render_template("erro_diretorio.html"), 503
    if tokens.consumir(s.banco, token, tokens.DEFINIR_EMAIL, agora) is None:
        return render_template("link_invalido.html"), 410
    s.banco.remover_email_pendente(uid)
    s.banco.auditar("publico", "email_definido", uid, email, agora)
    nova = tokens.emitir(s.banco, tokens.DEFINIR_SENHA, uid, s.cfg.token_ttl_hours, agora)
    return redirect(url_for("publico.definir_senha_form", token=nova))


@bp.get("/definir-senha/<token>")
def definir_senha_form(token):
    s = svc()
    uid = tokens.validar(s.banco, token, tokens.DEFINIR_SENHA, s.agora())
    if uid is None:
        return render_template("link_invalido.html"), 410
    return render_template("definir_senha.html", uid=uid, erros=[])


@bp.post("/definir-senha/<token>")
def definir_senha(token):
    s = svc()
    if not s.limite_token.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    agora = s.agora()
    uid = tokens.validar(s.banco, token, tokens.DEFINIR_SENHA, agora)
    if uid is None:
        return render_template("link_invalido.html"), 410
    senha = request.form.get("senha", "")
    erros = contas.problemas_senha(senha)
    if senha != request.form.get("confirmacao", ""):
        erros.append("as duas senhas devem ser iguais")
    if erros:
        return render_template("definir_senha.html", uid=uid, erros=erros), 400
    try:
        s.diretorio.definir_senha(uid, senha)
    except ErroDiretorio as e:
        log.error("falha ao definir senha de %s: %s", uid, e)
        return render_template("erro_diretorio.html"), 503
    tokens.consumir(s.banco, token, tokens.DEFINIR_SENHA, agora)
    s.banco.invalidar_tokens(tokens.DEFINIR_SENHA, uid, agora)
    s.banco.auditar(uid, "senha_definida", uid, "", agora)
    sid = s.banco.solicitacao_aprovada_do_uid(uid)
    if sid is not None:
        s.banco.auditar(uid, "senha_definida", f"sol:{sid}", "", agora)
    # login do usuário: sem session.clear() (preserva sessão admin), CSRF novo
    session.pop("csrf_token", None)
    session["usuario"] = uid
    session.permanent = True
    flash("Senha definida.")
    return redirect(url_for("conta.home"))


def _conta_do_link(token: str) -> dict | None:
    """Conta do LDAP do link confirmar_dados válido. Levanta ErroDiretorio."""
    s = svc()
    uid = tokens.validar(s.banco, token, tokens.CONFIRMAR_DADOS, s.agora())
    return s.diretorio.obter_conta(uid) if uid else None


def _completa(conta: dict) -> bool:
    return bool(conta["cn"] and conta["cpf"] and conta["mail"] and conta["telefone"])


def _tela_confirmar(conta, token, erro=None, status=200):
    return render_template("confirmar_dados.html", conta=conta, token=token, completa=_completa(conta), erro=erro,
                           privacidade=svc().tema.privacidade_html), status


def _seguir_para_senha(s, token: str, uid: str):
    """Consome o link de confirmação, audita o consentimento e leva à tela de definir senha."""
    agora = s.agora()
    if tokens.consumir(s.banco, token, tokens.CONFIRMAR_DADOS, agora) is None:
        return render_template("link_invalido.html"), 410
    ua = request.headers.get("User-Agent", "")[:300]
    s.banco.auditar(uid, "dados_confirmados", uid,
                    f"aviso {s.tema.privacidade_versao[:12]} · IP {ip_cliente()} · {ua}", agora)
    senha = tokens.emitir(s.banco, tokens.DEFINIR_SENHA, uid, s.cfg.token_ttl_hours, agora)
    return redirect(url_for("publico.definir_senha_form", token=senha))


def _conta_ou_erro(token: str):
    """(conta, None) se o link vale; senão (None, resposta de erro): 503 se o LDAP falhou, 410 se o link não vale."""
    try:
        conta = _conta_do_link(token)
    except ErroDiretorio as e:
        log.error("falha ao ler a conta do link de confirmação de dados: %s", e)
        return None, (render_template("erro_diretorio.html"), 503)
    if conta is None:
        return None, (render_template("link_invalido.html"), 410)
    return conta, None


@bp.get("/confirmar-dados/<token>")
def confirmar_dados_form(token):
    conta, erro = _conta_ou_erro(token)
    if erro:
        return erro
    return _tela_confirmar(conta, token)


@bp.post("/confirmar-dados/<token>")
def confirmar_dados(token):
    s = svc()
    if not s.limite_token.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    conta, erro = _conta_ou_erro(token)
    if erro:
        return erro
    if not _completa(conta):
        return _tela_confirmar(conta, token, "Faltam dados no seu cadastro: use \"Preciso corrigir\".", 400)
    if request.form.get("consentimento") != "sim":
        return _tela_confirmar(conta, token, MSG_CONSENTIMENTO, 400)
    return _seguir_para_senha(s, token, conta["uid"])


def tela_corrigir(form, erros=None, status=200):
    return render_template("corrigir_dados.html", form=form, erros=erros or {},
                           privacidade=svc().tema.privacidade_html), status


def form_da_conta(conta: dict) -> dict:
    return {"nome": conta["cn"], "cpf": cpf(conta["cpf"]), "email": conta["mail"],
            "telefone": telefone(conta["telefone"]), "justificativa": ""}


@bp.get("/confirmar-dados/<token>/corrigir")
def corrigir_dados_form(token):
    conta, erro = _conta_ou_erro(token)
    if erro:
        return erro
    return tela_corrigir(form_da_conta(conta))


def registrar_alteracao(s, conta: dict, dados: dict, alterados: list[str], sufixo: str = "") -> int | None:
    """Grava a correção de dados. E-mail novo: aguarda confirmação por link no endereço novo (o admin só é avisado
    depois); senão fica pendente e o admin é avisado já. Retorna o id, ou None se o e-mail de confirmação falhou."""
    agora = s.agora()
    email_novo = "email" in alterados
    consentimento = dict(versao_aviso=s.tema.privacidade_versao, texto_aviso=s.tema.privacidade_texto,
                         ip=ip_cliente(), user_agent=request.headers.get("User-Agent", "")[:300], agora=agora,
                         email_confirmado=False)
    sid = s.banco.criar_alteracao(dados, uid=conta["uid"], organizacao=conta["ou"], consentimento=consentimento,
                                  aguardando=email_novo)
    if email_novo:
        token = tokens.emitir(s.banco, tokens.CONFIRMAR_EMAIL, f"sol:{sid}", s.cfg.token_ttl_hours, agora)
        if not s.enviar("confirmar_email", dados["email"], nome=dados["nome"],
                        link=s.link(f"/confirmar-email/{token}"), validade=s.cfg.token_ttl_hours):
            s.banco.remover_solicitacao(sid)
            return None
    s.banco.auditar(conta["uid"], "alteracao_solicitada", f"sol:{sid}", f"campos: {', '.join(alterados)}{sufixo}",
                    agora)
    if not email_novo:
        s.enviar("nova_solicitacao", s.cfg.admin_notify_email, nome=dados["nome"], email=dados["email"],
                 link=s.link(f"/admin/solicitacao/{sid}"), alteracao=True)
    return sid


@bp.post("/confirmar-dados/<token>/corrigir")
def corrigir_dados(token):
    s = svc()
    if not s.limite_token.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    conta, erro = _conta_ou_erro(token)
    if erro:
        return erro
    form = {c: request.form.get(c, "") for c in CAMPOS}
    dados, erros = contas.validar_formulario(form, justificativa_opcional=True)
    if erros:
        return tela_corrigir(form, erros, 400)
    if request.form.get("consentimento") != "sim":
        return tela_corrigir(form, {"geral": MSG_CONSENTIMENTO}, 400)
    alterados = contas.campos_alterados(conta, dados)
    if not alterados:
        return _seguir_para_senha(s, token, conta["uid"])
    agora = s.agora()
    # consome antes de gravar: quem perde a corrida não cria uma segunda alteração
    if tokens.consumir(s.banco, token, tokens.CONFIRMAR_DADOS, agora) is None:
        return render_template("link_invalido.html"), 410
    if registrar_alteracao(s, conta, dados, alterados) is None:
        return render_template("erro_envio.html"), 503
    return render_template("alteracao_recebida.html", email_novo=dados["email"] if "email" in alterados else None)


def _convite_aberto(token: str) -> dict | None:
    """Solicitação do convite se o link é válido e o convite ainda não foi aceito nem cancelado."""
    s = svc()
    alvo = tokens.validar(s.banco, token, tokens.CONVITE, s.agora())
    sol = s.banco.obter(int(alvo.removeprefix("sol:"))) if alvo else None
    return sol if sol and sol["status"] == "convidado" else None


def _tela_convite(form, erros=None, status=200, email_fixo=None):
    return render_template("convite.html", form=form, erros=erros or {}, email_fixo=email_fixo,
                           privacidade=svc().tema.privacidade_html), status


@bp.get("/convite/<token>")
def convite_form(token):
    sol = _convite_aberto(token)
    if sol is None:
        return render_template("link_invalido.html"), 410
    if sol["origem"] == "convite_email":
        return _tela_convite({c: "" for c in CAMPOS}, email_fixo=sol["email"])
    return _tela_convite({"nome": sol["nome"], "cpf": cpf(sol["cpf"]), "email": sol["email"],
                          "telefone": telefone(sol["telefone"]), "justificativa": ""})


@bp.post("/convite/<token>")
def convite_aceitar(token):
    s = svc()
    if not s.limite_token.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    sol = _convite_aberto(token)
    if sol is None:
        return render_template("link_invalido.html"), 410
    if sol["origem"] == "convite_email":
        return _preencher_convite_email(s, sol, token)
    form = {c: request.form.get(c, "") for c in CAMPOS}
    dados, erros = contas.validar_formulario(form, justificativa_opcional=True)
    if erros:
        return _tela_convite(form, erros, 400)
    if request.form.get("consentimento") != "sim":
        return _tela_convite(form, {"geral": MSG_CONSENTIMENTO}, 400)
    sid, agora = sol["id"], s.agora()
    ip, ua = ip_cliente(), request.headers.get("User-Agent", "")[:300]
    alterados = [c for c in ("nome", "cpf", "email") if dados[c] != sol[c]]
    consentimento = dict(versao_aviso=s.tema.privacidade_versao, texto_aviso=s.tema.privacidade_texto, ip=ip,
                         user_agent=ua, agora=agora, email_confirmado="email" not in alterados)
    if not alterados:
        return _aceitar_sem_mudancas(s, sol, dados, token, consentimento)

    uid = contas.derivar_nomes(dados["nome"])["uid"] if "nome" in alterados else sol["uid_sugerido"]
    status, confirmado_em = ("aguardando_confirmacao", None) if "email" in alterados else ("pendente", iso(agora))
    # reivindica (com o consentimento, no mesmo passo) antes de emitir o token de confirmação: quem perde a
    # corrida não deixa token válido, e o prazo de aguardando_confirmacao já conta do aceite
    if not s.banco.aceitar_convite(sid, dados, ip=ip, user_agent=ua, uid_sugerido=uid, status=status,
                                   confirmado_em=confirmado_em, consentimento=consentimento):
        return render_template("link_invalido.html"), 410
    if status == "aguardando_confirmacao":
        token_email = tokens.emitir(s.banco, tokens.CONFIRMAR_EMAIL, f"sol:{sid}", s.cfg.token_ttl_hours, agora)
        if not s.enviar("confirmar_email", dados["email"], nome=dados["nome"],
                        link=s.link(f"/confirmar-email/{token_email}"), validade=s.cfg.token_ttl_hours):
            s.banco.invalidar_tokens(tokens.CONFIRMAR_EMAIL, f"sol:{sid}", agora)
            s.banco.devolver_convite(sol)
            return render_template("erro_envio.html"), 503
    tokens.consumir(s.banco, token, tokens.CONVITE, agora)
    if status == "pendente":  # com e-mail novo, quem encerra o anterior é a confirmação do e-mail
        s.banco.expirar_anteriores(dados["cpf"], dados["email"], sid)
    s.banco.auditar("convite", "convite_alterado", f"sol:{sid}",
                    f"campos: {', '.join(alterados)}; uid do convite: {sol['uid_sugerido']}", agora)
    if status == "aguardando_confirmacao":
        return render_template("enviado.html")
    s.enviar("nova_solicitacao", s.cfg.admin_notify_email, nome=dados["nome"], email=dados["email"],
             link=s.link(f"/admin/solicitacao/{sid}"))
    return render_template("email_confirmado.html")


def _preencher_convite_email(s, sol, token):
    """Convite por e-mail: a pessoa preenche nome/CPF/telefone e a solicitação vai para aprovação."""
    form = {c: request.form.get(c, "") for c in CAMPOS}
    form["email"] = sol["email"]  # vale o e-mail do convite, comprovado pelo link
    dados, erros = contas.validar_formulario(form, justificativa_opcional=True)
    if erros:
        return _tela_convite(form, erros, 400, sol["email"])
    if request.form.get("consentimento") != "sim":
        return _tela_convite(form, {"geral": MSG_CONSENTIMENTO}, 400, sol["email"])
    sid, agora = sol["id"], s.agora()
    ip, ua = ip_cliente(), request.headers.get("User-Agent", "")[:300]
    consentimento = dict(versao_aviso=s.tema.privacidade_versao, texto_aviso=s.tema.privacidade_texto, ip=ip,
                         user_agent=ua, agora=agora, email_confirmado=True)
    uid = contas.derivar_nomes(dados["nome"])["uid"]
    if not s.banco.aceitar_convite(sid, dados, ip=ip, user_agent=ua, uid_sugerido=uid, status="pendente",
                                   confirmado_em=iso(agora), consentimento=consentimento):
        return render_template("link_invalido.html"), 410
    tokens.consumir(s.banco, token, tokens.CONVITE, agora)
    s.banco.expirar_anteriores(dados["cpf"], dados["email"], sid)
    s.banco.auditar("convite", "convite_preenchido", f"sol:{sid}", "", agora)
    s.enviar("nova_solicitacao", s.cfg.admin_notify_email, nome=dados["nome"], email=dados["email"],
             link=s.link(f"/admin/solicitacao/{sid}"))
    return render_template("convite_recebido.html")


def _aceitar_sem_mudancas(s, sol, dados, token, consentimento):
    """Dados conferidos sem mudança: a conta é criada na hora e a pessoa segue para definir a senha."""
    sid, agora = sol["id"], consentimento["agora"]
    # grava os dados e reivindica (convidado -> aprovando) num único UPDATE condicional
    if not s.banco.aceitar_convite(sid, dados, ip=consentimento["ip"], user_agent=consentimento["user_agent"],
                                   uid_sugerido=sol["uid_sugerido"], status="aprovando", confirmado_em=iso(agora)):
        return render_template("link_invalido.html"), 410
    try:
        aprovacao.criar_conta(s, sid, volta_para="convidado", uid=sol["uid_sugerido"], org=sol["organizacao"],
                              ator="convite")
    except ErroDiretorio as e:
        log.error("falha ao criar a conta do convite %s: %s", sid, e)
        return render_template("erro_diretorio.html"), 503
    s.banco.registrar_consentimento(sid, **consentimento)
    tokens.consumir(s.banco, token, tokens.CONVITE, agora)
    s.banco.auditar("convite", "convite_aceito", f"sol:{sid}", "", agora)
    senha = tokens.emitir(s.banco, tokens.DEFINIR_SENHA, sol["uid_sugerido"], s.cfg.token_ttl_hours, agora)
    return redirect(url_for("publico.definir_senha_form", token=senha))
