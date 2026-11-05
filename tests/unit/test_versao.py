def test_versao_padrao_dev(monkeypatch):
    monkeypatch.delenv("APP_VERSION", raising=False)
    import importlib
    import app
    importlib.reload(app)
    assert app.__version__ == "dev"
