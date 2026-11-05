from pathlib import Path

from app import create_app
from tests.fakes import FakeCorreio, FakeDiretorio, config_teste, template_teste


def test_healthz(amb):
    r = amb.client.get("/healthz")
    assert r.status_code == 200 and r.json["status"] == "ok"


def test_logo_ausente_404(amb):
    assert amb.client.get("/tema/logo.png").status_code == 404


def test_logo_do_template(tmp_path):
    d = template_teste(tmp_path)
    (d / "logo.png").write_bytes(b"\x89PNG\r\n")
    app = create_app(config_teste(tmp_path), diretorio=FakeDiretorio(), correio=FakeCorreio(), testing=True)
    r = app.test_client().get("/tema/logo.png")
    assert r.status_code == 200 and r.mimetype == "image/png"


EXEMPLO = Path(__file__).resolve().parents[2] / "templates-exemplo" / "exemplo"
ICONE = '<link rel="icon" href="/favicon.ico" sizes="any">'
ICONE_PNG = '<link rel="icon" type="image/png" href="/tema/favicon.png">'
APPLE = '<link rel="apple-touch-icon" href="/tema/favicon.png">'


def test_favicon_padrao(amb):
    r = amb.client.get("/favicon.ico")
    assert r.status_code == 200 and r.mimetype == "image/vnd.microsoft.icon"
    assert r.headers["Cache-Control"] == "public, max-age=86400"
    assert r.data == (Path(__file__).resolve().parents[2] / "app" / "tema_padrao" / "favicon.ico").read_bytes()
    assert amb.client.get("/tema/favicon.png").status_code == 404


def test_favicon_do_template(tmp_path):
    d = template_teste(tmp_path)
    (d / "favicon.ico").write_bytes(b"ico-do-tema")
    (d / "favicon.png").write_bytes(b"\x89PNG-do-tema")
    c = create_app(config_teste(tmp_path), diretorio=FakeDiretorio(), correio=FakeCorreio(), testing=True).test_client()
    assert c.get("/favicon.ico").data == b"ico-do-tema"
    r = c.get("/tema/favicon.png")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data == b"\x89PNG-do-tema"
    assert r.headers["Cache-Control"] == "public, max-age=86400"


def test_head_sem_png_so_tem_o_ico(amb):
    for caminho in ("/", "/admin/login"):
        html = amb.client.get(caminho).text
        assert ICONE in html and ICONE_PNG not in html and APPLE not in html


def test_head_com_png(tmp_path):
    d = template_teste(tmp_path)
    (d / "favicon.png").write_bytes(b"\x89PNG")
    c = create_app(config_teste(tmp_path), diretorio=FakeDiretorio(), correio=FakeCorreio(), testing=True).test_client()
    for caminho in ("/", "/admin/login"):
        html = c.get(caminho).text
        assert ICONE in html and ICONE_PNG in html and APPLE in html


def test_head_do_template_exemplo_sem_logo_nem_favicon(tmp_path):
    """O tema de exemplo não traz logo nem favicon: cai no favicon padrão e mostra o nome do tema."""
    c = create_app(config_teste(tmp_path, template_dir=EXEMPLO), diretorio=FakeDiretorio(), correio=FakeCorreio(),
                   testing=True).test_client()
    padrao = Path(__file__).resolve().parents[2] / "app" / "tema_padrao" / "favicon.ico"
    for caminho in ("/", "/admin/login"):
        html = c.get(caminho).text
        assert ICONE in html and ICONE_PNG not in html and APPLE not in html
        assert '<span class="nome">Minha Plataforma</span>' in html and "/tema/logo.png" not in html
    assert c.get("/favicon.ico").data == padrao.read_bytes()
    assert c.get("/tema/logo.png").status_code == 404


def test_gunicorn_sem_access_log():
    """O access log gravaria tokens das URLs (/confirmar-email/<t>, /definir-senha/<t>)."""
    entrypoint = Path(__file__).resolve().parents[2] / "docker-entrypoint.sh"
    assert "--access-logfile" not in entrypoint.read_text(encoding="utf-8")


def test_cabecalhos_de_seguranca(amb):
    h = amb.client.get("/").headers
    assert h["X-Frame-Options"] == "DENY"
    assert h["Content-Security-Policy"] == "frame-ancestors 'none'"
    assert h["X-Content-Type-Options"] == "nosniff"
    assert h["Referrer-Policy"] == "same-origin"
