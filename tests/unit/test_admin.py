import pytest

from tests.fakes import auditoria
from tests.unit.test_publico import _solicitar


def _pendente(amb):
    amb.dir.contas.setdefault("existente", dict(uid="existente", cn="E", mail="e@y", ou="CLIENTE-A", cpf="9",
                                                telefone="", senha=None))  # cliente CLIENTE-A já existe
    _solicitar(amb)
    amb.client.post(amb.correio.caminho_do_link())  # confirmação de e-mail é por POST
    [sol] = amb.banco.buscar("", "pendente", 1)
    return sol["id"]


def _login(amb, uid="chefe", senha="Chefe#123"):
    return amb.client.post("/admin/login", data={"uid": uid, "senha": senha})


def test_painel_exige_login(amb):
    r = amb.client.get("/admin/")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_login_invalido(amb):
    assert _login(amb, senha="errada").status_code == 401
    assert amb.client.get("/admin/").status_code == 302


def test_login_ok_lista_pendentes(amb):
    sid = _pendente(amb)
    assert _login(amb).status_code == 302
    r = amb.client.get("/admin/")
    assert r.status_code == 200 and f"/admin/solicitacao/{sid}" in r.text


def test_detalhe_mostra_consentimento_e_clientes(amb):
    amb.dir.contas["x"] = dict(uid="x", cn="X", mail="x@y", ou="CLIENTE-B", cpf="0", telefone="", senha=None)
    sid = _pendente(amb)
    _login(amb)
    r = amb.client.get(f"/admin/solicitacao/{sid}")
    assert r.status_code == 200 and "CLIENTE-B" in r.text and "mariasouza" in r.text
    assert "Consentimento" in r.text


def test_aprovar_cria_conta_e_envia_link(amb):
    sid = _pendente(amb)
    _login(amb)
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "__nova__",
                        "organizacao_nova": "CLIENTE-A", "confirmar_nova": "sim", "uid": "mariasouza"})
    assert r.status_code == 302
    conta = amb.dir.contas["mariasouza"]
    assert conta["ou"] == "CLIENTE-A" and conta["cpf"] == "52998224725" and conta["telefone"] == "+5511912345678"
    sol = amb.banco.obter(sid)
    assert (sol["status"], sol["uid_final"], sol["organizacao"], sol["decidido_por"], sol["link_enviado"]) == \
           ("aprovada", "mariasouza", "CLIENTE-A", "chefe", 1)
    email = amb.correio.enviados[-1]
    assert email["para"] == "maria@exemplo.org" and "/definir-senha/" in email["texto"]
    assert "aprovar" in [a["acao"] for a in auditoria(amb.banco)]


def test_aprovar_cliente_novo_exige_confirmacao(amb):
    sid = _pendente(amb)
    _login(amb)
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar",
                        data={"organizacao": "__nova__", "organizacao_nova": "NOVA", "uid": "mariasouza"})
    assert r.status_code == 400 and "mariasouza" not in amb.dir.contas


def test_aprovar_cliente_fora_da_lista_exige_confirmacao(amb):
    sid = _pendente(amb)
    _login(amb)
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "Desconhecida", "uid": "mariasouza"})
    assert r.status_code == 400 and "mariasouza" not in amb.dir.contas
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar",
                        data={"organizacao": "Desconhecida", "confirmar_nova": "sim", "uid": "mariasouza"})
    assert r.status_code == 302 and amb.dir.contas["mariasouza"]["ou"] == "Desconhecida"


def test_aprovar_uid_em_uso(amb):
    amb.dir.contas["mariasouza"] = dict(uid="mariasouza", cn="Outra", mail="o@y", ou="CLIENTE-A", cpf="1",
                                        telefone="", senha=None)
    sid = _pendente(amb)
    _login(amb)
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert r.status_code == 409
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza2"})
    assert r.status_code == 302 and "mariasouza2" in amb.dir.contas


def test_aprovar_cpf_existente_exige_confirmar_outra_pessoa(amb):
    amb.dir.contas["msouza"] = dict(uid="msouza", cn="M", mail="m@y", ou="CLIENTE-A", cpf="52998224725",
                                    telefone="", senha=None)
    sid = _pendente(amb)
    _login(amb)
    dados = {"organizacao": "CLIENTE-A", "uid": "mariasouza"}
    assert amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data=dados).status_code == 409
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={**dados, "confirmar_outra_pessoa": "sim"})
    assert r.status_code == 302


def test_aprovar_ldap_fora(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.dir.falhar = True
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert r.status_code == 503 and amb.banco.obter(sid)["status"] == "pendente"


def test_aprovar_falha_ao_criar_conta_devolve_a_pendente(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.dir.falhar_criacao = True
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert r.status_code == 503 and amb.banco.obter(sid)["status"] == "pendente"
    amb.dir.falhar_criacao = False
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert r.status_code == 302


def test_aprovar_solicitacao_ja_reivindicada(amb):
    sid = _pendente(amb)
    _login(amb)
    assert amb.banco.reivindicar(sid) is True
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert r.status_code == 409 and "mariasouza" not in amb.dir.contas


def test_aprovar_smtp_fora_e_reenviar(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.correio.falhar = True
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert amb.banco.obter(sid)["link_enviado"] == 0 and "mariasouza" in amb.dir.contas
    assert "link não enviado" in amb.client.get(f"/admin/solicitacao/{sid}").text
    amb.correio.falhar = False
    amb.client.post(f"/admin/solicitacao/{sid}/reenviar")
    assert amb.banco.obter(sid)["link_enviado"] == 1


def test_aprovar_duas_vezes(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    r = amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "outro"})
    assert r.status_code == 409


@pytest.mark.parametrize("avisar,emails_extras", [("sim", 1), ("", 0)])
def test_rejeitar(amb, avisar, emails_extras):
    sid = _pendente(amb)
    _login(amb)
    antes = len(amb.correio.enviados)
    r = amb.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"motivo": "fora do escopo", "avisar": avisar})
    assert r.status_code == 302
    sol = amb.banco.obter(sid)
    assert sol["status"] == "rejeitada" and sol["motivo"] == "fora do escopo"
    assert len(amb.correio.enviados) - antes == emails_extras


def test_rejeitar_solicitacao_em_aprovacao(amb):
    sid = _pendente(amb)
    _login(amb)
    assert amb.banco.reivindicar(sid) is True
    r = amb.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"motivo": "x"})
    assert r.status_code == 409 and "não está pendente" in r.text
    assert amb.banco.obter(sid)["status"] == "aprovando"


def test_rejeitar_e_atomico(amb, monkeypatch):
    """Aprovação reivindica entre a leitura e a escrita da rejeição: a rejeição não pode sobrescrever."""
    sid = _pendente(amb)
    _login(amb)
    lida = amb.banco.obter(sid)
    amb.banco.reivindicar(sid)
    monkeypatch.setattr(amb.banco, "obter", lambda _sid: dict(lida))
    r = amb.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"motivo": "x", "avisar": "sim"})
    assert r.status_code == 409
    monkeypatch.undo()
    assert amb.banco.obter(sid)["status"] == "aprovando"


def test_detalhe_em_aprovacao_permite_destravar(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.banco.reivindicar(sid)
    assert "Voltar para pendente" in amb.client.get(f"/admin/solicitacao/{sid}").text


def test_destravar_volta_para_pendente(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.banco.reivindicar(sid)
    r = amb.client.post(f"/admin/solicitacao/{sid}/destravar")
    assert r.status_code == 302
    assert amb.banco.obter(sid)["status"] == "pendente"
    ultimo = auditoria(amb.banco)[0]
    assert (ultimo["ator"], ultimo["acao"], ultimo["alvo"]) == ("chefe", "destravar", f"sol:{sid}")


def test_destravar_so_em_aprovacao(amb):
    sid = _pendente(amb)
    _login(amb)
    assert amb.client.post(f"/admin/solicitacao/{sid}/destravar").status_code == 409
    assert amb.banco.obter(sid)["status"] == "pendente"
    assert "Voltar para pendente" not in amb.client.get(f"/admin/solicitacao/{sid}").text


def test_destravar_exige_login(amb):
    sid = _pendente(amb)
    amb.banco.reivindicar(sid)
    r = amb.client.post(f"/admin/solicitacao/{sid}/destravar")
    assert r.status_code == 302 and "/admin/login" in r.headers["Location"]
    assert amb.banco.obter(sid)["status"] == "aprovando"


def test_rejeitar_aviso_falho_aparece_no_painel(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.correio.falhar = True
    r = amb.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"motivo": "x", "avisar": "sim"},
                        follow_redirects=True)
    assert "falha ao enviar o aviso por e-mail" in r.text and amb.banco.obter(sid)["status"] == "rejeitada"


def test_busca_e_reset(amb):
    amb.dir.contas["antigo"] = dict(uid="antigo", cn="Antigo Usuario", mail="antigo@y", ou="CLIENTE-A", cpf="1",
                                    telefone="", senha=None)
    amb.dir.contas["semmail"] = dict(uid="semmail", cn="Sem Mail", mail="", ou="", cpf="2", telefone="", senha=None)
    _login(amb)
    r = amb.client.get("/admin/contas?q=antigo")
    assert r.status_code == 200 and "antigo@y" in r.text
    amb.client.post("/admin/contas/antigo/reset")
    email = amb.correio.enviados[-1]
    assert email["para"] == "antigo@y" and "/definir-senha/" in email["texto"]
    antes = len(amb.correio.enviados)
    r = amb.client.post("/admin/contas/semmail/reset", follow_redirects=True)
    assert "cadastre o e-mail" in r.text and len(amb.correio.enviados) == antes
    assert amb.client.post("/admin/contas/ninguem/reset").status_code == 404


def test_reset_e_definir_senha(amb):
    amb.dir.contas["antigo"] = dict(uid="antigo", cn="Antigo Usuario", mail="antigo@y", ou="CLIENTE-A", cpf="1",
                                    telefone="", senha=None)
    _login(amb)
    amb.client.post("/admin/contas/antigo/reset")
    caminho = amb.correio.caminho_do_link()
    amb.client.post(caminho, data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    assert amb.dir.contas["antigo"]["senha"] == "Nova#Senha1"


def test_sair(amb):
    _login(amb)
    amb.client.post("/admin/sair")
    assert amb.client.get("/admin/").status_code == 302


def test_csrf_ativo_fora_de_teste(tmp_path):
    from app import create_app
    from tests.fakes import FakeCorreio, FakeDiretorio, config_teste, template_teste
    template_teste(tmp_path)
    app = create_app(config_teste(tmp_path), diretorio=FakeDiretorio(), correio=FakeCorreio())
    assert app.test_client().post("/admin/login", data={"uid": "x", "senha": "y"}).status_code == 400


def _acoes(amb, sid):
    return [(h["acao"], h["detalhe"]) for h in amb.banco.historico(sid)]


def test_historico_erro_ldap_na_criacao(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.dir.falhar_criacao = True
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert amb.banco.obter(sid)["status"] == "pendente"
    assert ("erro_ldap", "uid=mariasouza org=CLIENTE-A: ldap fora do ar") in _acoes(amb, sid)
    r = amb.client.get(f"/admin/solicitacao/{sid}")
    assert "Histórico" in r.text and "erro_ldap" in r.text and "uid=mariasouza org=CLIENTE-A: ldap fora do ar" in r.text
    assert 'class="erro"' in r.text


def test_historico_erro_ldap_ao_consultar(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.dir.falhar = True
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert [a for a, _ in _acoes(amb, sid)][-1] == "erro_ldap"


def test_historico_aprovacao_ok(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    acoes = _acoes(amb, sid)
    assert [a for a, _ in acoes] == ["solicitacao_criada", "email_confirmado", "aprovar", "link_enviado"]
    detalhe = dict(acoes)["aprovar"]
    assert "uid=mariasouza" in detalhe and "org=CLIENTE-A" in detalhe and "uidNumber=10002" in detalhe
    r = amb.client.get(f"/admin/solicitacao/{sid}")
    assert "uid=mariasouza" in r.text and "chefe" in r.text


def test_historico_falha_envio_link(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.correio.falhar = True
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    assert [a for a, _ in _acoes(amb, sid)][-1] == "falha_envio_link"


def test_historico_aprovacao_bloqueada(amb):
    amb.dir.contas["mariasouza"] = dict(uid="mariasouza", cn="Outra", mail="o@y", ou="CLIENTE-A", cpf="1",
                                        telefone="", senha=None)
    sid = _pendente(amb)
    _login(amb)
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "Nova", "uid": "mariasouza2"})
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar",
                    data={"organizacao": "CLIENTE-A", "uid": "Inválido!", "confirmar_nova": "sim"})
    bloqueios = [d for a, d in _acoes(amb, sid) if a == "aprovacao_bloqueada"]
    assert len(bloqueios) == 3 and "mariasouza já existe" in bloqueios[0]
    assert "cliente novo" in bloqueios[1]


def test_historico_rejeicao_com_falha_do_aviso(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.correio.falhar = True
    amb.client.post(f"/admin/solicitacao/{sid}/rejeitar", data={"motivo": "x", "avisar": "sim"})
    assert [a for a, _ in _acoes(amb, sid)][-2:] == ["rejeitar", "falha_envio_aviso"]


def test_historico_senha_definida(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    amb.client.post(amb.correio.caminho_do_link(), data={"senha": "Nova#Senha1", "confirmacao": "Nova#Senha1"})
    [ultimo] = amb.banco.historico(sid)[-1:]
    assert (ultimo["ator"], ultimo["acao"]) == ("mariasouza", "senha_definida")
    assert "Nova#Senha1" not in amb.client.get(f"/admin/solicitacao/{sid}").text


def _varias(amb, n):
    ids = []
    for i in range(n):
        dados = {"nome": f"Pessoa {i:02d}", "cpf": f"{i:011d}", "email": f"p{i}@exemplo.org",
                 "telefone": "+5511912345678", "justificativa": f"motivo numero {i}"}
        sid = amb.banco.criar_solicitacao(dados, uid_sugerido=f"p{i}", ip="", user_agent="", versao_aviso="v",
                                          texto_aviso="", agora=amb.relogio())
        amb.banco.confirmar_email(sid, amb.relogio())
        ids.append(sid)
    return ids


def _ids_na_lista(html):
    import re
    return [int(x) for x in re.findall(r'href="/admin/solicitacao/(\d+)"', html)]


def test_lista_paginada(amb):
    ids = _varias(amb, 60)
    _login(amb)
    paginas = [_ids_na_lista(amb.client.get(f"/admin/?pagina={p}").text) for p in (1, 2, 3)]
    assert [len(p) for p in paginas] == [25, 25, 10]
    assert sorted(sum(paginas, [])) == sorted(ids)
    assert "60 resultados" in amb.client.get("/admin/").text
    assert _ids_na_lista(amb.client.get("/admin/?pagina=999").text) == paginas[2]
    assert _ids_na_lista(amb.client.get("/admin/?pagina=abc").text) == paginas[0]


@pytest.mark.parametrize("termo", ["000.000.000-07", "p7@exemplo", "pessoa 07", "numero 7"])
def test_lista_busca(amb, termo):
    ids = _varias(amb, 12)
    _login(amb)
    r = amb.client.get("/admin/", query_string={"q": termo})
    assert ids[7] in _ids_na_lista(r.text)
    assert len(_ids_na_lista(r.text)) <= 2


def test_lista_busca_curinga_literal(amb):
    _varias(amb, 3)
    _login(amb)
    assert _ids_na_lista(amb.client.get("/admin/?q=%25").text) == []
    assert _ids_na_lista(amb.client.get("/admin/?q=pess_a&status=todos").text) == []


def test_lista_filtro_padrao_e_invalido(amb):
    [a, b] = _varias(amb, 2)
    amb.banco.atualizar(b, status="aprovada", uid_final="p1")
    _login(amb)
    assert _ids_na_lista(amb.client.get("/admin/").text) == [a]
    assert _ids_na_lista(amb.client.get("/admin/?status=xyz").text) == [a]
    assert _ids_na_lista(amb.client.get("/admin/?status=aprovada").text) == [b]
    assert _ids_na_lista(amb.client.get("/admin/?status=todos").text) == [b, a]


def test_lista_paginacao_preserva_busca_e_filtro(amb):
    _varias(amb, 30)
    _login(amb)
    r = amb.client.get("/admin/?q=exemplo&status=todos")
    assert "/admin/?q=exemplo&amp;status=todos&amp;pagina=2" in r.text


def test_lista_badges_de_status(amb):
    [a, b, c] = _varias(amb, 3)
    amb.banco.atualizar(b, status="aprovada", uid_final="p1")
    amb.banco.atualizar(c, status="rejeitada")
    _login(amb)
    r = amb.client.get("/admin/?q=exemplo&status=aprovada")
    for rotulo, n in [("Todos", 3), ("Pendente", 1), ("Em aprovação", 0), ("Aprovada", 1), ("Rejeitada", 1),
                      ("Expirada", 0), ("Aguardando confirmação", 0)]:
        assert f"{rotulo} <span class=\"contagem\">{n}</span>" in r.text, rotulo
    assert 'href="/admin/?q=exemplo&amp;status=aprovada" aria-current="page"' in r.text
    assert r.text.count('aria-current="page"') == 1
    assert 'href="/admin/?q=exemplo&amp;status=pendente"' in r.text
    r = amb.client.get("/admin/?q=p1@")
    assert "Todos <span class=\"contagem\">1</span>" in r.text


def test_lista_avisa_solicitacao_em_aprovacao(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.banco.reivindicar(sid)
    r = amb.client.get("/admin/")
    assert "1 solicitação em aprovação" in r.text and 'href="/admin/?status=aprovando"' in r.text
    assert sid in _ids_na_lista(amb.client.get("/admin/?status=aprovando").text)


def test_lista_pagina_gigante_mostra_a_ultima(amb):
    _varias(amb, 30)
    _login(amb)
    ultima = _ids_na_lista(amb.client.get("/admin/?pagina=2").text)
    r = amb.client.get("/admin/?pagina=99999999999999999999")
    assert r.status_code == 200 and _ids_na_lista(r.text) == ultima


def test_historico_reenvio_usa_as_mesmas_acoes_do_link(amb):
    sid = _pendente(amb)
    _login(amb)
    amb.client.post(f"/admin/solicitacao/{sid}/aprovar", data={"organizacao": "CLIENTE-A", "uid": "mariasouza"})
    amb.correio.falhar = True
    amb.client.post(f"/admin/solicitacao/{sid}/reenviar")
    assert _acoes(amb, sid)[-1] == ("falha_envio_link", "maria@exemplo.org")
    amb.correio.falhar = False
    amb.client.post(f"/admin/solicitacao/{sid}/reenviar")
    assert _acoes(amb, sid)[-1] == ("link_enviado", "maria@exemplo.org")
    assert '<tr class="erro">' in amb.client.get(f"/admin/solicitacao/{sid}").text


def test_lista_explica_que_status_e_pelos_badges(amb):
    _login(amb)
    assert "para filtrar por status, use os botões abaixo" in amb.client.get("/admin/").text


def test_painel_usa_layout_largo_e_publico_estreito(amb):
    sid = _pendente(amb)
    assert '<main class="estreito">' in amb.client.get("/").text
    assert '<main class="estreito">' in amb.client.get("/admin/login").text
    _login(amb)
    for url in ("/admin/", f"/admin/solicitacao/{sid}", "/admin/contas", "/admin/contas?q=x"):
        assert '<main class="largo">' in amb.client.get(url).text, url


def test_lista_formata_status_datas_cpf_e_telefone(amb):
    [a, b] = _varias(amb, 2)
    amb.banco.atualizar(b, status="aprovada", uid_final="p1", organizacao="CLIENTE-A")
    _login(amb)
    r = amb.client.get("/admin/?status=todos")
    assert '<span class="pill st-pendente">Pendente</span>' in r.text
    assert '<span class="pill st-aprovada">Aprovada</span>' in r.text
    assert "04/11/2026 09:00" in r.text and "2026-11-04T" not in r.text  # 12:00 UTC em America/Sao_Paulo
    assert "000.000.000-01" in r.text and "+55 (11) 91234-5678" in r.text
    assert '<span class="mudo">p0</span>' in r.text


@pytest.mark.parametrize("status,rotulo", [
    ("aprovando", "Em aprovação"), ("rejeitada", "Rejeitada"), ("expirada", "Expirada"),
    ("aguardando_confirmacao", "Aguardando confirmação"),
])
def test_lista_rotulos_das_pilulas(amb, status, rotulo):
    [a] = _varias(amb, 1)
    amb.banco.atualizar(a, status=status)
    _login(amb)
    r = amb.client.get("/admin/?status=todos")
    assert f'<span class="pill st-{status}">{rotulo}</span>' in r.text


def test_lista_busca_em_linha_com_limpar(amb):
    _login(amb)
    r = amb.client.get("/admin/?status=todos")
    assert 'placeholder="Buscar por nome, CPF, e-mail, telefone, justificativa, usuário, cliente…"' in r.text
    assert ">Limpar</a>" not in r.text
    r = amb.client.get("/admin/?q=maria&status=todos")
    assert '<a href="/admin/?status=todos">Limpar</a>' in r.text
    assert '<input type="hidden" name="status" value="todos">' in r.text


def test_detalhe_formata_datas(amb):
    sid = _pendente(amb)
    _login(amb)
    r = amb.client.get(f"/admin/solicitacao/{sid}")
    assert "04/11/2026 09:00" in r.text and "2026-11-04T" not in r.text
    assert "529.982.247-25" in r.text and "+55 (11) 91234-5678" in r.text
    assert '<span class="pill st-pendente">Pendente</span>' in r.text


def test_lista_id_em_badge_na_primeira_coluna(amb):
    [a] = _varias(amb, 1)
    _login(amb)
    r = amb.client.get("/admin/")
    assert "<tr><th>#</th><th>Nome</th>" in r.text
    assert f'<td class="id"><a class="id-badge" href="/admin/solicitacao/{a}"' in r.text
    assert f">#{a}</a></td>" in r.text
    assert f'<span class="id-badge">#{a}</span>' in amb.client.get(f"/admin/solicitacao/{a}").text


def test_tema_exemplo_tem_o_mesmo_layout_do_painel(tmp_path):
    from pathlib import Path

    from app import create_app
    from tests.fakes import FakeCorreio, FakeDiretorio, config_teste
    exemplo = Path(__file__).resolve().parents[2] / "templates-exemplo" / "exemplo"
    app = create_app(config_teste(tmp_path, template_dir=exemplo), diretorio=FakeDiretorio(),
                     correio=FakeCorreio(), testing=True)
    c = app.test_client()
    assert '<main class="estreito">' in c.get("/").text
    c.post("/admin/login", data={"uid": "chefe", "senha": "Chefe#123"})
    r = c.get("/admin/")
    assert '<main class="largo">' in r.text and "www.exemplo.org" in r.text
    for classe in ("main.largo", ".id-badge", ".pill", "table.lista", "form.busca", "dl.dados", ".sr-only"):
        assert classe in r.text, classe
