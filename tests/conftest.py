from types import SimpleNamespace

import pytest

from app import create_app
from tests.fakes import FakeCorreio, FakeDiretorio, Relogio, config_teste, template_teste


@pytest.fixture
def amb(tmp_path):
    """App com LDAP e SMTP falsos, relógio fixo e CSRF desligado."""
    template_teste(tmp_path)
    cfg = config_teste(tmp_path)
    d, c, r = FakeDiretorio(), FakeCorreio(), Relogio()
    app = create_app(cfg, diretorio=d, correio=c, relogio=r, testing=True)
    return SimpleNamespace(app=app, client=app.test_client(), dir=d, correio=c, relogio=r,
                           banco=app.extensions["signup"].banco, cfg=cfg)
