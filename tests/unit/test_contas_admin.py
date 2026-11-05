import re

import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login


def _conta(amb, uid, cn="Pessoa Teste", mail="", ou="", cpf="", grupos=()):
    amb.dir.contas[uid] = dict(uid=uid, cn=cn, mail=mail, ou=ou, cpf=cpf, telefone="", senha=None,
                               grupos=list(grupos))


def _uids_na_lista(html):
    return re.findall(r'<input type="checkbox" name="uid" value="([^"]+)"', html)


@pytest.fixture
def adm(amb):
    _login(amb)
    return amb


def test_contas_exige_login(amb):
    r = amb.client.get("/admin/contas")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_contas_lista_tudo_sem_busca_paginada(adm):
    for i in range(60):
        _conta(adm, f"u{59 - i:03d}", mail=f"u{i}@exemplo.org")
    paginas = [_uids_na_lista(adm.client.get(f"/admin/contas?pagina={p}").text) for p in (1, 2, 3)]
    assert [len(p) for p in paginas] == [25, 25, 10]
    assert sum(paginas, []) == [f"u{i:03d}" for i in range(60)]  # ordenadas por uid
    r = adm.client.get("/admin/contas")
    assert "60 contas" in r.text and '<main class="largo">' in r.text
    assert "/admin/contas?pagina=2" in r.text
    assert _uids_na_lista(adm.client.get("/admin/contas?pagina=999").text) == paginas[2]
    assert _uids_na_lista(adm.client.get("/admin/contas?pagina=abc").text) == paginas[0]


@pytest.mark.parametrize("termo", ["joão", "JOAO SIL", "jsilva@exem", "111.444.777-35", "11144477735", "cliente-b",
                                   "jsil"])
def test_contas_busca_por_trecho(adm, termo):
    _conta(adm, "jsilva", cn="João Silva", mail="jsilva@exemplo.org", ou="CLIENTE-B", cpf="11144477735")
    _conta(adm, "outra", cn="Maria Souza", mail="maria@exemplo.org", ou="CLIENTE-A", cpf="52998224725")
    r = adm.client.get("/admin/contas", query_string={"q": termo})
    assert _uids_na_lista(r.text) == ["jsilva"]
    assert "1 conta" in r.text


def test_contas_busca_sem_resultado(adm):
    _conta(adm, "jsilva", cn="João Silva")
    r = adm.client.get("/admin/contas?q=ninguem")
    assert _uids_na_lista(r.text) == [] and "Nenhuma conta encontrada." in r.text
    assert '<a href="/admin/contas">Limpar</a>' in r.text


def test_contas_filtro_por_cliente_com_contagens(adm):
    _conta(adm, "ana", cn="Ana Lima", ou="CLIENTE-A")
    _conta(adm, "bia", cn="Bia Lima", ou="CLIENTE-A")
    _conta(adm, "caio", cn="Caio Lima", ou="CLIENTE-B")
    _conta(adm, "duda", cn="Duda Lima")
    _conta(adm, "edu", cn="Edu Souza", ou="CLIENTE-A")
    r = adm.client.get("/admin/contas?q=lima")
    for rotulo, n in [("Todos", 4), ("CLIENTE-A", 2), ("CLIENTE-B", 1), ("Sem cliente", 1)]:
        assert f'{rotulo} <span class="contagem">{n}</span>' in r.text, rotulo
    assert 'href="/admin/contas?q=lima" aria-current="page"' in r.text
    assert r.text.count('aria-current="page"') == 1
    r = adm.client.get("/admin/contas?q=lima&cliente=CLIENTE-A&pagina=1")
    assert _uids_na_lista(r.text) == ["ana", "bia"]
    assert 'href="/admin/contas?q=lima&amp;cliente=CLIENTE-A" aria-current="page"' in r.text
    assert _uids_na_lista(adm.client.get("/admin/contas?cliente=__sem__").text) == ["duda"]
    assert _uids_na_lista(adm.client.get("/admin/contas?cliente=NaoExiste").text) == \
        ["ana", "bia", "caio", "duda", "edu"]


def test_contas_paginacao_preserva_busca_e_cliente(adm):
    for i in range(30):
        _conta(adm, f"p{i:03d}", cn="Pessoa Lima", ou="CLIENTE-A")
    r = adm.client.get("/admin/contas?q=lima&cliente=CLIENTE-A")
    assert "/admin/contas?q=lima&amp;cliente=CLIENTE-A&amp;pagina=2" in r.text


def test_contas_mostra_sem_email_grupos_e_acao(adm):
    _conta(adm, "semmail", cn="Sem Mail", grupos=["Usuario"])
    _conta(adm, "muitos", cn="Muitos Grupos", mail="m@exemplo.org", ou="CLIENTE-A",
           grupos=["Usuario", "wiki", "grafana", "sip", "rokia"])
    r = adm.client.get("/admin/contas")
    assert '<strong class="erro">sem e-mail</strong>' in r.text
    assert '<td class="grupos" title="grafana, rokia, sip, Usuario, wiki"><span>grafana</span> <span class="mudo">+4</span></td>' in r.text
    assert 'action="/admin/contas/muitos/reset"' in r.text
    assert 'class="icone" title="Enviar link de redefinição" aria-label="Enviar link de redefinição"><svg' in r.text
    assert 'disabled class="icone" title="Sem e-mail: cadastre o e-mail antes" aria-label="Sem e-mail: cadastre o e-mail antes"' in r.text


def test_contas_ldap_fora(adm):
    adm.dir.falhar = True
    assert adm.client.get("/admin/contas").status_code == 503


def _tres(amb):
    _conta(amb, "ana", cn="Ana Lima", mail="ana@exemplo.org", ou="CLIENTE-A")
    _conta(amb, "bia", cn="Bia Lima", mail="bia@exemplo.org", ou="CLIENTE-A")
    _conta(amb, "caio", cn="Caio Lima", ou="CLIENTE-A")  # sem e-mail


def test_lista_tem_formulario_do_lote_com_filtro_atual(adm):
    _tres(adm)
    r = adm.client.get("/admin/contas?q=lima&cliente=CLIENTE-A")
    assert '<form method="post" id="lote" action="/admin/contas/reset-lote/confirmar"' in r.text
    assert '<input type="hidden" name="q" value="lima">' in r.text
    assert '<input type="hidden" name="cliente" value="CLIENTE-A">' in r.text
    assert 'name="todos_do_filtro" value="sim"' in r.text and "todas as 3 contas do filtro" in r.text
    dica = "Enviar link de redefinição às selecionadas"
    assert f'<button type="submit" class="icone" title="{dica}" aria-label="{dica}"><svg' in r.text


def test_selecionar_todas_marca_as_caixas_das_linhas(adm):
    _tres(adm)
    r = adm.client.get("/admin/contas?cliente=CLIENTE-A")
    assert 'id="todos_do_filtro"' in r.text
    assert "getElementById('todos_do_filtro')" in r.text
    assert "input[name=uid][form=lote]" in r.text


def test_confirmar_lote_separa_sem_email(adm):
    _tres(adm)
    r = adm.client.post("/admin/contas/reset-lote/confirmar", data={"uid": ["ana", "bia", "caio"]})
    assert r.status_code == 200
    com, sem = r.text.split("Sem e-mail")
    assert "ana@exemplo.org" in com and "bia@exemplo.org" in com and "caio" not in com
    assert "caio" in sem
    assert "2 contas receberão o link" in r.text
    for uid in ("ana", "bia", "caio"):
        assert f'<input type="hidden" name="uid" value="{uid}">' in r.text
    assert 'action="/admin/contas/reset-lote"' in r.text
    assert adm.correio.enviados == []


def test_confirmar_lote_sem_selecao(adm):
    _tres(adm)
    r = adm.client.post("/admin/contas/reset-lote/confirmar", data={})
    assert r.status_code == 400 and "Selecione ao menos uma conta" in r.text


def test_confirmar_lote_acima_do_limite_pede_filtro(adm):
    for i in range(201):
        _conta(adm, f"p{i:03d}", mail=f"p{i}@exemplo.org", ou="CLIENTE-A")
    r = adm.client.post("/admin/contas/reset-lote/confirmar", data={"todos_do_filtro": "sim", "cliente": "CLIENTE-A"})
    assert r.status_code == 400 and "201 contas" in r.text and "filtre" in r.text
    r = adm.client.post("/admin/contas/reset-lote", data={"todos_do_filtro": "sim", "cliente": "CLIENTE-A"})
    assert r.status_code == 400 and adm.correio.enviados == []
    r = adm.client.post("/admin/contas/reset-lote/confirmar", data={"todos_do_filtro": "sim", "q": "p1"})
    assert r.status_code == 200  # p1, p10..p19, p100..p199 = 111 contas


def test_reset_lote_envia_e_reporta_pulada(adm):
    # aceite 27: 3 contas (uma sem e-mail) → 2 links e 1 pulada; cada link define a senha
    _tres(adm)
    r = adm.client.post("/admin/contas/reset-lote", data={"uid": ["ana", "bia", "caio"]})
    assert r.status_code == 200
    assert "Enviados: 2" in r.text and "Falhas de envio: 0" in r.text and "Pulados: 1" in r.text
    assert sorted(e["para"] for e in adm.correio.enviados) == ["ana@exemplo.org", "bia@exemplo.org"]
    for i, uid in enumerate(("ana", "bia")):
        caminho = adm.correio.caminho_do_link(i)
        assert caminho.startswith("/definir-senha/")
        adm.client.post(caminho, data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
        assert adm.dir.contas[uid]["senha"] == "Nova#Senha1"
    acoes = [(a["acao"], a["alvo"], a["detalhe"]) for a in auditoria(adm.banco)]
    assert ("reset_senha", "ana", "ok") in acoes and ("reset_senha", "bia", "ok") in acoes
    assert ("reset_lote", "contas", "enviados=2 falhas=0 sem_email=1 nao_encontradas=0") in acoes


def test_reset_lote_todos_do_filtro(adm):
    # aceite 28: todas as contas CLIENTE-A com e-mail (de todas as páginas)
    _tres(adm)
    for i in range(30):
        _conta(adm, f"p{i:03d}", cn="Pessoa", mail=f"p{i}@exemplo.org", ou="CLIENTE-A")
    _conta(adm, "outro", cn="Outro Cliente", mail="outro@exemplo.org", ou="CLIENTE-B")
    r = adm.client.post("/admin/contas/reset-lote/confirmar", data={"todos_do_filtro": "sim", "cliente": "CLIENTE-A"})
    assert "32 contas receberão o link" in r.text
    assert '<input type="hidden" name="todos_do_filtro" value="sim">' in r.text
    assert '<input type="hidden" name="cliente" value="CLIENTE-A">' in r.text
    r = adm.client.post("/admin/contas/reset-lote", data={"todos_do_filtro": "sim", "cliente": "CLIENTE-A",
                                                          "uid": ["outro"]})
    assert "Enviados: 32" in r.text and "Pulados: 1" in r.text
    destinos = {e["para"] for e in adm.correio.enviados}
    assert len(destinos) == 32 and "outro@exemplo.org" not in destinos
    adm.correio.enviados.clear()
    adm.client.post("/admin/contas/reset-lote", data={"todos_do_filtro": "sim", "q": "lima", "cliente": "CLIENTE-A"})
    assert sorted(e["para"] for e in adm.correio.enviados) == ["ana@exemplo.org", "bia@exemplo.org"]


def test_reset_lote_ignora_uid_invalido_e_mail_do_formulario(adm):
    _tres(adm)
    r = adm.client.post("/admin/contas/reset-lote", data={
        "uid": ["ana", "ana", "*)(uid=*", "Bia", "../x", "ninguem"], "mail": "atacante@exemplo.org",
        "email": "atacante@exemplo.org"})
    assert r.status_code == 200
    assert [e["para"] for e in adm.correio.enviados] == ["ana@exemplo.org"]
    assert "Enviados: 1" in r.text and "Pulados: 1" in r.text  # ninguem: conta não encontrada
    assert "não encontrada" in r.text
    assert "*)(uid=*" not in r.text
    r = adm.client.post("/admin/contas/reset-lote", data={"uid": ["*)(uid=*"]})
    assert r.status_code == 400


def test_reset_lote_falha_de_envio(adm):
    _tres(adm)
    adm.correio.falhar = True
    r = adm.client.post("/admin/contas/reset-lote", data={"uid": ["ana", "caio"]})
    assert "Enviados: 0" in r.text and "Falhas de envio: 1" in r.text and "Pulados: 1" in r.text
    acoes = [(a["acao"], a["alvo"], a["detalhe"]) for a in auditoria(adm.banco)]
    assert ("reset_senha", "ana", "falha_envio") in acoes
    assert ("reset_lote", "contas", "enviados=0 falhas=1 sem_email=1 nao_encontradas=0") in acoes


def test_reset_lote_exige_login_e_ldap(amb):
    for url in ("/admin/contas/reset-lote/confirmar", "/admin/contas/reset-lote"):
        r = amb.client.post(url, data={"uid": ["ana"]})
        assert r.status_code == 302 and "/admin/login" in r.headers["Location"]
    _login(amb)
    amb.dir.falhar = True
    for url in ("/admin/contas/reset-lote/confirmar", "/admin/contas/reset-lote"):
        assert amb.client.post(url, data={"uid": ["ana"]}).status_code == 503


def test_reset_lote_exige_csrf_fora_de_teste(tmp_path):
    from app import create_app
    from tests.fakes import FakeCorreio, FakeDiretorio, config_teste, template_teste
    template_teste(tmp_path)
    app = create_app(config_teste(tmp_path), diretorio=FakeDiretorio(), correio=FakeCorreio())
    c = app.test_client()
    with c.session_transaction() as sessao:
        sessao["admin"] = "chefe"
    for url in ("/admin/contas/reset-lote/confirmar", "/admin/contas/reset-lote"):
        assert c.post(url, data={"uid": ["ana"]}).status_code == 400
