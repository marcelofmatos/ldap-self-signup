import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, abort, request, send_file
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

__version__ = os.environ.get("APP_VERSION", "dev")


def create_app(cfg, *, banco=None, diretorio=None, correio=None, tema=None, relogio=None,
               testing: bool = False) -> Flask:
    from . import formatos, lote
    from .banco import Banco
    from .correio import Correio
    from .diretorio import Diretorio
    from .ratelimit import LimiteTaxa
    from .servicos import Servicos, na_hora
    from .tema import Tema
    from .web.admin import rotulo_acao
    from .web.admin import bp as bp_admin
    from .web.conta import bp as bp_conta
    from .web.publico import bp as bp_publico

    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=cfg.secret_key,
        SESSION_COOKIE_SECURE=cfg.cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        TESTING=testing,
        WTF_CSRF_ENABLED=not testing,
        WTF_CSRF_TIME_LIMIT=None,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if cfg.trusted_proxies:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=cfg.trusted_proxies, x_proto=1, x_host=1)

    @app.before_request
    def limite_do_upload():
        # registrado antes do CSRFProtect, que lê o formulário: só o upload da planilha passa de 64 KiB
        if request.endpoint == "admin.lote_upload":
            request.max_content_length = lote.MAX_BYTES + 64 * 1024

    CSRFProtect(app)

    tema = tema or Tema(cfg.template_dir)
    app.jinja_loader = tema.carregador_paginas()
    if banco is None:
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        banco = Banco(cfg.data_dir / "signup.db")
    servicos = Servicos(
        cfg=cfg, banco=banco, diretorio=diretorio or Diretorio(cfg), correio=correio or Correio(cfg),
        tema=tema, relogio=relogio or (lambda: datetime.now(timezone.utc)),
        limite_form=LimiteTaxa(*cfg.rate_limit_form),
        limite_login=LimiteTaxa(*cfg.rate_limit_login),
        limite_token=LimiteTaxa(*cfg.rate_limit_login),
        **({"em_segundo_plano": na_hora} if testing else {}),
    )
    app.extensions["signup"] = servicos
    app.jinja_env.globals.update(tema=tema.dados, tema_logo=tema.logo is not None,
                                 tema_favicon_png=tema.favicon_png is not None, versao=__version__)
    fuso = ZoneInfo(cfg.timezone_exibicao)
    app.jinja_env.filters.update(data=lambda valor: formatos.data(valor, fuso), cpf=formatos.cpf,
                                 telefone=formatos.telefone, cpf_mascarado=formatos.cpf_mascarado,
                                 acao=rotulo_acao)
    app.register_blueprint(bp_publico)
    app.register_blueprint(bp_admin)
    app.register_blueprint(bp_conta)

    @app.after_request
    def cabecalhos_de_seguranca(resposta):
        resposta.headers["X-Frame-Options"] = "DENY"
        resposta.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
        resposta.headers["X-Content-Type-Options"] = "nosniff"
        # same-origin mantém o Referer que o CSRF do Flask-WTF exige em HTTPS.
        resposta.headers["Referrer-Policy"] = "same-origin"
        return resposta

    @app.get("/healthz")
    def healthz():
        servicos.banco.ok()
        return {"status": "ok", "versao": __version__}

    @app.get("/tema/logo.png")
    def logo():
        if tema.logo is None:
            abort(404)
        return send_file(tema.logo, mimetype="image/png")

    @app.get("/favicon.ico")
    def favicon():
        return send_file(tema.favicon_ico, mimetype="image/vnd.microsoft.icon", max_age=86400)

    @app.get("/tema/favicon.png")
    def favicon_png():
        if tema.favicon_png is None:
            abort(404)
        return send_file(tema.favicon_png, mimetype="image/png", max_age=86400)

    return app
