import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login as _login_admin


def _conta(amb, **over):
    c = dict(uid="mariasouza", cn="Maria Souza", mail="maria@exemplo.org", ou="CLIENTE-A", cpf="52998224725",
             telefone="+5511912345678", senha="Nova#Senha1", grupos=["Usuario", "Arquivos"])
    c.update(over)
    amb.dir.contas[c["uid"]] = c


def _entrar(amb, uid="mariasouza", senha="Nova#Senha1"):
    return amb.client.post("/entrar", data={"uid": uid, "senha": senha})


def test_home_exige_login(amb):
    for url in ("/minha-conta", "/minha-conta/corrigir"):
        r = amb.client.get(url)
        assert r.status_code == 302 and r.headers["Location"].endswith("/entrar")


def test_entrar_e_ver_home(amb):
    _conta(amb)
    r = _entrar(amb)
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    html = amb.client.get("/minha-conta").text
    assert "Maria Souza" in html and "***.982.247-**" in html and "529.982.247-25" not in html
    assert "maria@exemplo.org" in html and "+55 (11) 91234-5678" in html and "CLIENTE-A" in html
    assert "Arquivos, Usuario" in html
    assert "/minha-conta/corrigir" in html
    assert auditoria(amb.banco)[0]["acao"] == "login_usuario"


def test_home_mostra_servicos_como_cards(amb):
    _conta(amb)
    amb.app.extensions["signup"].tema.dados["servicos"] = [
        {"rotulo": "Arquivos", "url": "https://arq.x", "icone": "arquivos", "descricao": ""},
        {"rotulo": "Wiki", "url": "https://w.x", "icone": "wiki", "descricao": "Documentação interna"}]
    _entrar(amb)
    html = amb.client.get("/minha-conta").text
    assert '<a class="servico" href="https://arq.x" target="_blank" rel="noopener noreferrer">' in html and "Arquivos" in html
    assert '<a class="servico" href="https://w.x" target="_blank" rel="noopener noreferrer">' in html and "Documentação interna" in html
    assert html.count("<svg") >= 2


def _tema_com_clientes(amb):
    s = amb.app.extensions["signup"]
    s.tema.dados["servicos"] = [{"rotulo": "Geral", "url": "https://g.x", "icone": "link", "descricao": ""}]
    s.tema.por_cliente = {"cliente-a": ({"Painel A": "https://a.x"}, [
        {"rotulo": "Painel A", "url": "https://a.x", "icone": "painel", "descricao": ""}])}


def test_home_mostra_servicos_gerais_e_do_cliente(amb):
    _tema_com_clientes(amb)
    _conta(amb)
    _entrar(amb)
    html = amb.client.get("/minha-conta").text
    assert "https://g.x" in html and "https://a.x" in html


@pytest.mark.parametrize("ou", ["CLIENTE-B", ""])
def test_home_nao_mostra_servico_de_outro_cliente(amb, ou):
    _tema_com_clientes(amb)
    _conta(amb, ou=ou)
    _entrar(amb)
    html = amb.client.get("/minha-conta").text
    assert "https://g.x" in html and "https://a.x" not in html


def test_senha_errada(amb):
    _conta(amb)
    r = _entrar(amb, senha="errada")
    assert r.status_code == 401 and "Usuário ou senha inválidos." in r.text
    assert amb.client.get("/minha-conta").status_code == 302


def test_entrar_logado_vai_para_home(amb):
    _conta(amb)
    _entrar(amb)
    r = amb.client.get("/entrar")
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")


def test_sair(amb):
    _conta(amb)
    _entrar(amb)
    r = amb.client.post("/sair")
    assert r.status_code == 302 and r.headers["Location"].endswith("/entrar")
    assert amb.client.get("/minha-conta").status_code == 302


def test_login_de_usuario_nao_derruba_sessao_admin(amb):
    _conta(amb)
    _login_admin(amb)
    _entrar(amb)
    assert amb.client.get("/admin/").status_code == 200
    amb.client.post("/sair")
    assert amb.client.get("/admin/").status_code == 200


def test_ldap_fora_no_login_e_na_home(amb):
    _conta(amb)
    _entrar(amb)
    amb.dir.falhar = True
    assert amb.client.get("/minha-conta").status_code == 503
    amb.client.post("/sair")
    assert _entrar(amb).status_code == 503


def test_conta_sumiu_desloga(amb):
    _conta(amb)
    _entrar(amb)
    del amb.dir.contas["mariasouza"]
    r = amb.client.get("/minha-conta")
    assert r.status_code == 302 and r.headers["Location"].endswith("/entrar")


def test_home_avisa_correcao_em_aberto(amb):
    _conta(amb)
    _entrar(amb)
    consent = dict(versao_aviso="v", texto_aviso="t", ip="1.1.1.1", user_agent="ua", agora=amb.relogio(),
                   email_confirmado=False)
    dados = dict(nome="Maria Souza", cpf="52998224725", email="maria@exemplo.org", telefone="+5521998765432",
                 justificativa="")
    amb.banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=consent)
    assert "Correção em análise" in amb.client.get("/minha-conta").text
    amb.banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=consent, aguardando=True)
    assert "Confirme seu novo e-mail" in amb.client.get("/minha-conta").text


def test_formulario_de_cadastro_tem_link_para_entrar(amb):
    assert 'href="/entrar"' in amb.client.get("/cadastro").text


def test_sessao_de_usuario_sobrevive_ao_login_e_logout_do_admin(amb):
    _conta(amb)
    _entrar(amb)
    _login_admin(amb)
    assert amb.client.get("/minha-conta").status_code == 200
    amb.client.post("/admin/sair")
    assert amb.client.get("/minha-conta").status_code == 200
    assert amb.client.get("/admin/").status_code == 302


def test_so_usuario_nao_acessa_admin(amb):
    _conta(amb)
    _entrar(amb)
    r = amb.client.get("/admin/")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_so_admin_nao_acessa_minha_conta(amb):
    _login_admin(amb)
    r = amb.client.get("/minha-conta")
    assert r.status_code == 302 and r.headers["Location"].endswith("/entrar")


def test_home_avisa_correcao_aprovando(amb):
    _conta(amb)
    _entrar(amb)
    consent = dict(versao_aviso="v", texto_aviso="t", ip="1.1.1.1", user_agent="ua", agora=amb.relogio(),
                   email_confirmado=False)
    dados = dict(nome="Maria Souza", cpf="52998224725", email="maria@exemplo.org", telefone="+5521998765432",
                 justificativa="")
    sid = amb.banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=consent)
    with amb.banco._con() as con:
        con.execute("UPDATE solicitacoes SET status='aprovando' WHERE id=?", (sid,))
    assert "Correção em análise" in amb.client.get("/minha-conta").text


def test_home_campo_vazio_mostra_nao_informado(amb):
    _conta(amb, telefone="")
    _entrar(amb)
    assert "não informado" in amb.client.get("/minha-conta").text


def test_uid_normalizado_no_login(amb):
    _conta(amb)
    r = _entrar(amb, uid=" MariaSouza ")
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")


def _form(**over):
    base = {"nome": "Maria da Silva Souza", "cpf": "529.982.247-25", "email": "maria@exemplo.org",
            "telefone": "(11) 91234-5678", "justificativa": "", "consentimento": "sim"}
    base.update(over)
    return base


def test_corrigir_pela_home_mostra_formulario_preenchido(amb):
    _conta(amb)
    _entrar(amb)
    html = amb.client.get("/minha-conta/corrigir").text
    assert 'value="Maria Souza"' in html and 'value="529.982.247-25"' in html


def test_corrigir_pela_home_sem_mudanca(amb):
    _conta(amb)
    _entrar(amb)
    r = amb.client.post("/minha-conta/corrigir", data=_form())
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    assert "Nenhuma alteração nos seus dados." in amb.client.get("/minha-conta").text
    assert amb.banco.buscar("", "pendente", 1) == []


def test_corrigir_telefone_pela_home(amb):
    _conta(amb)
    _entrar(amb)
    r = amb.client.post("/minha-conta/corrigir", data=_form(telefone="(21) 99876-5432"))
    assert r.status_code == 302
    home = amb.client.get("/minha-conta").text
    assert "Recebemos sua correção" in home and "Correção em análise" in home
    sol = amb.banco.buscar("", "pendente", 1)[0]
    assert sol["origem"] == "alteracao" and sol["telefone"] == "+5521998765432"
    assert amb.dir.contas["mariasouza"]["telefone"] == "+5511912345678"
    assert amb.correio.enviados[-1]["para"] == amb.cfg.admin_notify_email
    assert any(a["acao"] == "alteracao_solicitada" and "pela home" in a["detalhe"] for a in auditoria(amb.banco))


def test_corrigir_email_pela_home_exige_confirmacao(amb):
    _conta(amb)
    _entrar(amb)
    amb.client.post("/minha-conta/corrigir", data=_form(email="maria.nova@exemplo.org"))
    assert amb.correio.enviados[-1]["para"] == "maria.nova@exemplo.org"
    assert all(e["para"] != amb.cfg.admin_notify_email for e in amb.correio.enviados)
    assert amb.banco.buscar("", "pendente", 1) == []
    home = amb.client.get("/minha-conta").text
    assert "maria.nova@exemplo.org" in home and "confirmar o novo e-mail" in home
    assert "Confirme seu novo e-mail" in home
    assert amb.client.post(amb.correio.caminho_do_link()).status_code == 200
    assert amb.banco.buscar("", "pendente", 1)[0]["email"] == "maria.nova@exemplo.org"


def test_corrigir_pela_home_valida(amb):
    _conta(amb)
    _entrar(amb)
    assert amb.client.post("/minha-conta/corrigir", data=_form(cpf="123")).status_code == 400
    assert amb.client.post("/minha-conta/corrigir", data=_form(telefone="(21) 99876-5432",
                                                               consentimento="")).status_code == 400


def test_corrigir_email_pela_home_falha_no_envio(amb):
    _conta(amb)
    _entrar(amb)
    amb.correio.falhar = True
    r = amb.client.post("/minha-conta/corrigir", data=_form(email="maria.nova@exemplo.org"))
    assert r.status_code == 503
    assert amb.banco.alteracao_em_aberto("mariasouza") is None
    assert all(e["para"] != amb.cfg.admin_notify_email for e in amb.correio.enviados)


def test_corrigir_pela_home_anonimo_vai_para_o_login(amb):
    r = amb.client.post("/minha-conta/corrigir", data=_form(telefone="(21) 99876-5432"))
    assert r.status_code == 302 and r.headers["Location"].endswith("/entrar")


def test_corrigir_pela_home_respeita_limite(amb):
    _conta(amb)
    _entrar(amb)
    for _ in range(10):
        amb.client.post("/minha-conta/corrigir", data=_form(consentimento=""))
    assert amb.client.post("/minha-conta/corrigir", data=_form(consentimento="")).status_code == 429


def test_entrar_renova_csrf(amb):
    _conta(amb)
    with amb.client.session_transaction() as sess:
        sess["csrf_token"] = "velho"
    assert _entrar(amb).status_code == 302
    with amb.client.session_transaction() as sess:
        assert sess.get("csrf_token") != "velho"


def test_inicio_logado_oferece_ir_para_minha_conta(amb):
    _conta(amb)
    _entrar(amb)
    assert 'href="/minha-conta"' in amb.client.get("/").text


def _trocar(amb, atual="Nova#Senha1", senha="Outra#Senha2", confirmacao=None):
    return amb.client.post("/minha-conta/senha", data={
        "atual": atual, "senha": senha, "confirmacao": senha if confirmacao is None else confirmacao})


def test_trocar_senha_exige_login(amb):
    for r in (amb.client.get("/minha-conta/senha"), _trocar(amb)):
        assert r.status_code == 302 and r.headers["Location"].endswith("/entrar")


def test_home_tem_link_trocar_senha(amb):
    _conta(amb)
    _entrar(amb)
    assert 'href="/minha-conta/senha"' in amb.client.get("/minha-conta").text
    assert amb.client.get("/minha-conta/senha").status_code == 200


def test_trocar_senha_ok(amb):
    _conta(amb)
    _entrar(amb)
    r = _trocar(amb)
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    assert amb.dir.contas["mariasouza"]["senha"] == "Outra#Senha2"
    assert auditoria(amb.banco)[0]["acao"] == "senha_alterada"
    home = amb.client.get("/minha-conta")
    assert home.status_code == 200 and "Senha alterada." in home.text


def test_trocar_senha_atual_errada(amb):
    _conta(amb)
    _entrar(amb)
    r = _trocar(amb, atual="errada")
    assert r.status_code == 400 and "Senha atual incorreta." in r.text
    assert amb.dir.contas["mariasouza"]["senha"] == "Nova#Senha1"


def test_trocar_senha_fraca_ou_diferente(amb):
    _conta(amb)
    _entrar(amb)
    r = _trocar(amb, senha="fraca")
    assert r.status_code == 400 and "<li>" in r.text
    r = _trocar(amb, confirmacao="Outra#Senha3")
    assert r.status_code == 400 and "as duas senhas devem ser iguais" in r.text
    assert amb.dir.contas["mariasouza"]["senha"] == "Nova#Senha1"


def test_trocar_senha_invalida_link_definir_senha(amb):
    from app import tokens
    _conta(amb)
    _entrar(amb)
    tok = tokens.emitir(amb.banco, tokens.DEFINIR_SENHA, "mariasouza", 24, amb.relogio())
    assert _trocar(amb).status_code == 302
    assert amb.client.get(f"/definir-senha/{tok}").status_code == 410


def test_trocar_senha_respeita_limite(amb):
    _conta(amb)
    _entrar(amb)
    for _ in range(10):
        _trocar(amb, atual="errada")
    assert _trocar(amb, atual="errada").status_code == 429


def test_trocar_senha_ldap_fora(amb):
    _conta(amb)
    _entrar(amb)
    amb.dir.falhar = True
    assert _trocar(amb).status_code == 503


def test_todos_os_icones_renderizam_svg(amb):
    from app.tema import ICONES
    tpl = amb.app.jinja_env.from_string('{% from "_icones.html" import icone %}{{ icone(n) }}')
    for n in ICONES:
        assert "<svg" in tpl.render(n=n), n


def test_sair_fica_no_topo_ao_lado_do_titulo(amb):
    _conta(amb)
    _entrar(amb)
    html = amb.client.get("/minha-conta").text
    topo = html.split('<div class="topo-conta">', 1)[1].split("</div>", 1)[0]
    assert "<h1>Minha conta</h1>" in topo and 'action="/sair"' in topo and ">Sair</button>" in topo
    assert html.count('action="/sair"') == 1  # um só botão de sair, antes dos dados
    assert html.index('action="/sair"') < html.index('<dl class="dados">')


def test_entrar_tem_atalhos_em_badge(amb):
    html = amb.client.get("/entrar").text
    atalhos = html.split('<p class="badges">', 1)[1].split("</p>", 1)[0]
    assert '<a class="badge" href="/esqueci-senha">Esqueci minha senha</a>' in atalhos
    assert '<a class="badge" href="/cadastro">Solicitar acesso</a>' in atalhos


def test_inicio_logado_tem_badge_para_minha_conta(amb):
    _conta(amb)
    _entrar(amb)
    atalhos = amb.client.get("/").text.split('<p class="badges">', 1)[1].split("</p>", 1)[0]
    assert '<a class="badge" href="/minha-conta">Ir para minha conta</a>' in atalhos


def test_admin_ve_atalho_para_o_painel(amb):
    _conta(amb)
    amb.dir.admins["mariasouza"] = "Nova#Senha1"
    _entrar(amb)
    topo = amb.client.get("/minha-conta").text.split('<div class="topo-conta">', 1)[1].split("</div>", 1)[0]
    assert '<a class="badge" href="/admin/login?uid=mariasouza">Painel admin</a>' in topo


def test_usuario_comum_nao_ve_atalho_para_o_painel(amb):
    _conta(amb)
    _entrar(amb)
    assert "Painel admin" not in amb.client.get("/minha-conta").text


def test_login_do_painel_vem_com_usuario_preenchido(amb):
    html = amb.client.get("/admin/login?uid=MariaSouza").text
    assert 'name="uid" value="mariasouza"' in html


def test_login_do_painel_com_sessao_de_admin_vai_direto(amb):
    _login_admin(amb)
    r = amb.client.get("/admin/login")
    assert r.status_code == 302 and r.headers["Location"].endswith("/admin/")
