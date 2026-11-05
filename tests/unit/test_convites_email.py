from app import convites, tokens


def _valido(amb, caminho):
    token = caminho.removeprefix("/convite/")
    return tokens.validar(amb.banco, token, tokens.CONVITE, amb.relogio()) is not None


def test_criar_por_email_envia_link_valido(amb):
    s = amb.app.extensions["signup"]
    sid, enviado = convites.criar_por_email(s, "ana@exemplo.org", org="CLIENTE-A", admin="chefe")
    assert enviado is True
    sol = amb.banco.obter(sid)
    assert (sol["origem"], sol["status"], sol["link_enviado"]) == ("convite_email", "convidado", 1)
    assert len(amb.correio.enviados) == 1 and amb.correio.enviados[0]["para"] == "ana@exemplo.org"
    assert _valido(amb, amb.correio.caminho_do_link())
    acoes = [(h["acao"], h["detalhe"]) for h in amb.banco.historico(sid)]
    assert ("convite_criado", "email=ana@exemplo.org org=CLIENTE-A") in acoes
    assert ("convite_enviado", "ana@exemplo.org") in acoes


def test_segundo_convite_do_mesmo_email_substitui_o_primeiro(amb):
    s = amb.app.extensions["signup"]
    primeiro, _ = convites.criar_por_email(s, "ana@exemplo.org", org="CLIENTE-A", admin="chefe")
    link1 = amb.correio.caminho_do_link()
    segundo, _ = convites.criar_por_email(s, "ana@exemplo.org", org="CLIENTE-A", admin="chefe")
    assert not _valido(amb, link1)
    assert _valido(amb, amb.correio.caminho_do_link())
    assert amb.banco.obter(primeiro)["status"] == "expirada"
    assert amb.banco.obter(segundo)["status"] == "convidado"
    assert ("convite_cancelado", f"substituído pelo convite #{segundo}") in \
        [(h["acao"], h["detalhe"]) for h in amb.banco.historico(primeiro)]


def test_reenviar_convite_por_email_usa_o_modelo_sem_nome(amb):
    s = amb.app.extensions["signup"]
    sid, _ = convites.criar_por_email(s, "ana@exemplo.org", org="CLIENTE-A", admin="chefe")
    assert convites.enviar(s, sid, "chefe") is True
    assert len(amb.correio.enviados) == 2
    corpo = amb.correio.enviados[1]["texto"]
    assert "Olá!" in corpo and "None" not in corpo


def test_falha_de_envio_mantem_o_convite_sem_link_enviado(amb):
    s = amb.app.extensions["signup"]
    amb.correio.falhar = True
    sid, enviado = convites.criar_por_email(s, "ana@exemplo.org", org="CLIENTE-A", admin="chefe")
    assert enviado is False
    sol = amb.banco.obter(sid)
    assert (sol["status"], sol["link_enviado"]) == ("convidado", 0)
    assert ("falha_envio_convite", "ana@exemplo.org") in [(h["acao"], h["detalhe"]) for h in amb.banco.historico(sid)]
