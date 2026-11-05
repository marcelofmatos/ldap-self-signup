from tests.unit.test_admin import _login

DADOS = dict(nome="Ana Souza", cpf="52998224725", email="ana@exemplo.org", telefone="+5511987654321", justificativa="x")


def _conta(amb, uid="ana", **over):
    amb.dir.contas[uid] = dict(uid=uid, cn="Ana Souza", mail="ana@exemplo.org", ou="CLIENTE-A", cpf="52998224725",
                               telefone="+5511987654321", senha=None, grupos=["wiki", "grafana"])
    amb.dir.contas[uid].update(over)


def _convite(amb, uid, **dados):
    sid = amb.banco.criar_convite({**DADOS, **dados}, uid=uid, organizacao="CLIENTE-A", convidado_por="chefe",
                                  agora=amb.relogio())
    amb.banco.atualizar(sid, status="aprovada", uid_final=uid)
    return sid


def test_ficha_exige_admin(amb):
    _conta(amb)
    r = amb.client.get("/admin/contas/ana")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_ficha_inexistente_404(amb):
    _login(amb)
    assert amb.client.get("/admin/contas/ninguem").status_code == 404


def test_ficha_ldap_fora_503(amb):
    _conta(amb)
    _login(amb)
    amb.dir.falhar = True
    assert amb.client.get("/admin/contas/ana").status_code == 503


def test_ficha_mostra_dados(amb):
    _conta(amb)
    _login(amb)
    html = amb.client.get("/admin/contas/ana").get_data(as_text=True)
    for esperado in ("ana", "Ana Souza", "529.982.247-25", "ana@exemplo.org", "+55 (11) 98765-4321", "CLIENTE-A",
                     "grafana", "wiki"):
        assert esperado in html
    assert "/admin/contas/ana/reset" in html and "/admin/contas/ana/confirmacao" in html


def test_ficha_lista_solicitacoes_ligadas(amb):
    _conta(amb)
    _conta(amb, "bia")
    aprovada = _convite(amb, "ana")
    alteracao = amb.banco.criar_alteracao(
        DADOS, uid="ana", organizacao="CLIENTE-A",
        consentimento=dict(agora=amb.relogio(), versao_aviso="v", texto_aviso="t", ip="1.1.1.1", user_agent="x", email_confirmado=False))
    outra = _convite(amb, "bia")
    _login(amb)
    html = amb.client.get("/admin/contas/ana").get_data(as_text=True)
    assert f"/admin/solicitacao/{aprovada}" in html and f"/admin/solicitacao/{alteracao}" in html
    assert f"/admin/solicitacao/{outra}" not in html


def test_ficha_historico_com_rotulos(amb):
    _conta(amb)
    _conta(amb, "bia")
    sid = _convite(amb, "ana")
    agora = amb.relogio()
    amb.banco.auditar("ana", "login_usuario", "ana", "", agora)
    amb.banco.auditar("ana", "senha_alterada", "ana", "", agora)
    amb.banco.auditar("chefe", "reset_senha", "ana", "ok", agora)
    amb.banco.auditar("chefe", "aprovar", f"sol:{sid}", "", agora)
    amb.banco.auditar("sistema", "link_enviado", f"sol:{sid}", "", agora)
    amb.banco.auditar("bia", "login_usuario", "bia", "", agora)
    _login(amb)
    html = amb.client.get("/admin/contas/ana").get_data(as_text=True)
    assert "Entrou na área do usuário" in html and "Aprovou" in html and "Trocou a senha" in html
    assert html.count("Entrou na área do usuário") == 1  # o login de bia não aparece
    assert html.index("Enviou link de definir senha") < html.index("Entrou na área do usuário")  # mais recente 1º


def test_acao_sem_rotulo_mostra_codigo(amb):
    _conta(amb)
    amb.banco.auditar("x", "acao_inventada", "ana", "", amb.relogio())
    _login(amb)
    assert "acao_inventada" in amb.client.get("/admin/contas/ana").get_data(as_text=True)


def test_lista_tem_link_para_ficha(amb):
    _conta(amb)
    _login(amb)
    html = amb.client.get("/admin/contas").get_data(as_text=True)
    assert 'href="/admin/contas/ana"' in html and 'title="Ver ficha da conta"' in html


def test_rotas_de_lote_nao_sao_capturadas_como_uid(amb):
    _conta(amb)
    _login(amb)
    for rota in ("reset-lote", "reset-lote/confirmar", "confirmacao-lote", "confirmacao-lote/confirmar"):
        r = amb.client.post(f"/admin/contas/{rota}", data={"uid": "ana"})
        assert r.status_code != 405 and r.status_code != 404, rota
    assert amb.client.get("/admin/contas/confirmacao-lote").status_code in (404, 405)


def test_linha_de_erro_no_historico_fica_destacada(amb):
    _conta(amb)
    amb.banco.auditar("sistema", "erro_ldap", "ana", "falha", amb.relogio())
    _login(amb)
    html = amb.client.get("/admin/contas/ana").get_data(as_text=True)
    assert '<tr class="erro">' in html and "Erro no LDAP" in html


def test_ficha_sem_solicitacoes_nem_historico(amb):
    _conta(amb)
    _login(amb)
    r = amb.client.get("/admin/contas/ana")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    assert "Nenhuma solicitação ligada a esta conta." in html and "Sem registros." in html


def test_rotulos_dos_lotes():
    from app.web.admin import ROTULOS_ACAO
    assert ROTULOS_ACAO["reset_lote"] == "Reset de senha em lote"
    assert ROTULOS_ACAO["confirmacao_lote"] == "Confirmação de dados em lote"
