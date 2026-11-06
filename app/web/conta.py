import logging
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from .. import contas, tokens
from ..diretorio import ErroDiretorio
from ..servicos import ip_cliente, svc
from .publico import CAMPOS, MSG_CONSENTIMENTO, form_da_conta, registrar_alteracao, tela_corrigir

bp = Blueprint("conta", __name__)
log = logging.getLogger("ldap-self-signup")


def requer_usuario(f):
    @wraps(f)
    def envolvida(*args, **kwargs):
        if not session.get("usuario"):
            return redirect(url_for("conta.entrar"))
        return f(*args, **kwargs)
    return envolvida


def _ldap_fora(e: ErroDiretorio):
    log.error("erro no LDAP na área do usuário: %s", e)
    return render_template("erro_diretorio.html"), 503


def conta_logada():
    """(conta do LDAP, None) ou (None, resposta): 503 se o LDAP falhou; volta ao login se a conta sumiu."""
    try:
        conta = svc().diretorio.obter_conta(session["usuario"])
    except ErroDiretorio as e:
        return None, _ldap_fora(e)
    if conta is None:
        session.pop("usuario", None)
        return None, redirect(url_for("conta.entrar"))
    return conta, None


@bp.route("/entrar", methods=["GET", "POST"])
def entrar():
    if request.method == "GET" and session.get("usuario"):
        return redirect(url_for("conta.home"))
    s = svc()
    erro = None
    if request.method == "POST":
        if not s.limite_login.permitir(ip_cliente()):
            return render_template("limite.html"), 429
        uid = request.form.get("uid", "").strip().lower()
        try:
            ok = s.diretorio.autenticar(uid, request.form.get("senha", ""))
        except ErroDiretorio as e:
            return _ldap_fora(e)
        if ok:
            # sem session.clear(): uma sessão admin aberta no mesmo navegador continua valendo; CSRF novo a cada login
            session.pop("csrf_token", None)
            session["usuario"] = uid
            session.permanent = True
            s.banco.auditar(uid, "login_usuario", uid, "", s.agora())
            return redirect(url_for("conta.home"))
        erro = "Usuário ou senha inválidos."
    return render_template("conta/entrar.html", erro=erro), (401 if erro else 200)


@bp.post("/sair")
def sair():
    session.pop("usuario", None)
    return redirect(url_for("conta.entrar"))


@bp.get("/minha-conta")
@requer_usuario
def home():
    conta, resposta = conta_logada()
    if resposta:
        return resposta
    s = svc()
    try:
        grupos = s.diretorio.grupos_de(conta["uid"])
        admin = s.diretorio.e_admin(conta["uid"])
    except ErroDiretorio as e:
        return _ldap_fora(e)
    return render_template("conta/home.html", conta=conta, grupos=grupos, admin=admin,
                           servicos=s.tema.servicos_do_cliente(conta.get("ou")),
                           em_aberto=s.banco.alteracao_em_aberto(conta["uid"]))


@bp.get("/minha-conta/corrigir")
@requer_usuario
def corrigir_form():
    conta, resposta = conta_logada()
    if resposta:
        return resposta
    return tela_corrigir(form_da_conta(conta))


@bp.post("/minha-conta/corrigir")
@requer_usuario
def corrigir():
    s = svc()
    if not s.limite_token.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    conta, resposta = conta_logada()
    if resposta:
        return resposta
    form = {c: request.form.get(c, "") for c in CAMPOS}
    dados, erros = contas.validar_formulario(form, justificativa_opcional=True)
    if erros:
        return tela_corrigir(form, erros, 400)
    if request.form.get("consentimento") != "sim":
        return tela_corrigir(form, {"geral": MSG_CONSENTIMENTO}, 400)
    alterados = contas.campos_alterados(conta, dados)
    if not alterados:
        flash("Nenhuma alteração nos seus dados.")
        return redirect(url_for("conta.home"))
    if registrar_alteracao(s, conta, dados, alterados, " · pela home") is None:
        return render_template("erro_envio.html"), 503
    if "email" in alterados:
        flash(f"Recebemos sua correção. Enviamos um link para {dados['email']}: ela só segue para revisão depois "
              "que você confirmar o novo e-mail.")
    else:
        flash("Recebemos sua correção. Ela será revisada pela equipe.")
    return redirect(url_for("conta.home"))


@bp.route("/minha-conta/senha", methods=["GET", "POST"])
@requer_usuario
def trocar_senha():
    if request.method == "GET":
        return render_template("conta/trocar_senha.html", erros=[])
    s, uid = svc(), session["usuario"]
    if not s.limite_login.permitir(ip_cliente()):
        return render_template("limite.html"), 429
    nova = request.form.get("senha", "")
    try:
        if not s.diretorio.autenticar(uid, request.form.get("atual", "")):
            return render_template("conta/trocar_senha.html", erros=["Senha atual incorreta."]), 400
        erros = contas.problemas_senha(nova)
        if nova != request.form.get("confirmacao", ""):
            erros.append("as duas senhas devem ser iguais")
        if erros:
            return render_template("conta/trocar_senha.html", erros=erros), 400
        s.diretorio.definir_senha(uid, nova)
    except ErroDiretorio as e:
        return _ldap_fora(e)
    agora = s.agora()
    s.banco.invalidar_tokens(tokens.DEFINIR_SENHA, uid, agora)
    s.banco.auditar(uid, "senha_alterada", uid, "", agora)
    flash("Senha alterada.")
    return redirect(url_for("conta.home"))
