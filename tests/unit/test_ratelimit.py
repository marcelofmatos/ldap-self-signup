from app.ratelimit import LimiteTaxa


def test_limite_por_chave_e_janela():
    t = [0.0]
    lim = LimiteTaxa(2, 60, relogio=lambda: t[0])
    assert lim.permitir("a") and lim.permitir("a")
    assert not lim.permitir("a")
    assert lim.permitir("b")
    t[0] = 61.0
    assert lim.permitir("a")
