import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login
from tests.unit.test_convite_admin import CONVITE
from tests.unit.test_publico import FORM

ACEITE = {"nome": "Joana Pereira Lima", "cpf": "123.456.789-09", "email": "joana@exemplo.org",
          "telefone": "+55 (11) 98765-4321", "justificativa": "", "consentimento": "sim"}


@pytest.fixture
def conv(amb):
    """Convite criado pelo admin (que depois sai): devolve o caminho do link."""
    amb.dir.contas["existente"] = dict(uid="existente", cn="E", mail="e@y", ou="CLIENTE-A", cpf="9", telefone="",
                                       senha=None)
    _login(amb)
    assert amb.client.post("/admin/convidar", data=CONVITE).status_code == 302
    amb.client.post("/admin/sair")
    amb.link = amb.correio.caminho_do_link()
    [sol] = amb.banco.buscar("", "convidado", 1)
    amb.sid = sol["id"]
    return amb


def _aceitar(amb, **over):
    return amb.client.post(amb.link, data={**ACEITE, **over})


def _acoes(amb):
    return [(h["ator"], h["acao"], h["detalhe"]) for h in amb.banco.historico(amb.sid)]


def test_abrir_convite_mostra_dados_editaveis_e_formatados(conv):
    r = conv.client.get(conv.link)
    assert r.status_code == 200 and "Confira seus dados" in r.text
    for valor in ('value="Joana Pereira Lima"', 'value="123.456.789-09"', 'value="joana@exemplo.org"',
                  'value="+55 (11) 98765-4321"'):
        assert valor in r.text, valor
    assert 'name="justificativa"' in r.text and "Aviso de privacidade" in r.text
    assert 'name="consentimento"' in r.text and "checked" not in r.text
    assert conv.banco.obter(conv.sid)["status"] == "convidado"


def test_link_de_convite_invalido(amb):
    assert amb.client.get("/convite/nada").status_code == 410
    assert amb.client.post("/convite/nada", data=ACEITE).status_code == 410


def test_aceitar_sem_consentimento_nao_tem_efeito(conv):
    r = _aceitar(conv, consentimento="")
    assert r.status_code == 400 and "aviso de privacidade" in r.text
    assert conv.banco.obter(conv.sid)["status"] == "convidado" and conv.banco.consentimento(conv.sid) is None
    assert "joanalima" not in conv.dir.contas and conv.client.get(conv.link).status_code == 200


def test_aceitar_com_dado_invalido(conv):
    r = _aceitar(conv, cpf="123")
    assert r.status_code == 400 and "CPF inválido" in r.text and 'value="123"' in r.text
    assert conv.banco.obter(conv.sid)["status"] == "convidado"


def test_aceitar_sem_mudancas_cria_conta_e_leva_a_definir_senha(conv):
    r = _aceitar(conv, justificativa="Equipe do projeto novo.")
    assert r.status_code == 302 and "/definir-senha/" in r.headers["Location"]
    conta = conv.dir.contas["joanalima"]
    assert (conta["ou"], conta["cpf"], conta["mail"], conta["telefone"]) == \
           ("CLIENTE-A", "12345678909", "joana@exemplo.org", "+5511987654321")
    sol = conv.banco.obter(conv.sid)
    assert (sol["status"], sol["uid_final"], sol["organizacao"], sol["decidido_por"], sol["justificativa"]) == \
           ("aprovada", "joanalima", "CLIENTE-A", "convite", "Equipe do projeto novo.")
    c = conv.banco.consentimento(conv.sid)
    assert c["aceito_em"] == c["email_confirmado_em"] == "2026-11-04T12:00:00+00:00"
    assert c["versao_aviso"] == conv.app.extensions["signup"].tema.privacidade_versao
    assert [a for _, a, _ in _acoes(conv)][-2:] == ["aprovar", "convite_aceito"]
    assert ("convite", "aprovar") in [(a, b) for a, b, _ in _acoes(conv)]
    assert len(conv.correio.enviados) == 1  # sem e-mail: a senha é definida na hora
    caminho = r.headers["Location"].removeprefix("http://localhost")
    r = conv.client.post(caminho, data={"senha": "Joana#2026", "confirmacao": "Joana#2026"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/minha-conta")
    assert conv.dir.contas["joanalima"]["senha"] == "Joana#2026"
    assert conv.client.get(conv.link).status_code == 410  # convite usado


def test_aceitar_mudando_so_o_telefone_cria_a_conta(conv):
    assert _aceitar(conv, telefone="(21) 99999-0000").status_code == 302
    assert conv.dir.contas["joanalima"]["telefone"] == "+5521999990000"


def test_aceitar_mudando_o_nome_vai_para_o_admin(conv):
    r = _aceitar(conv, nome="Joana Pereira Souza")
    assert r.status_code == 200 and "joanalima" not in conv.dir.contas and "joanasouza" not in conv.dir.contas
    sol = conv.banco.obter(conv.sid)
    assert (sol["status"], sol["nome"], sol["uid_sugerido"], sol["organizacao"]) == \
           ("pendente", "Joana Pereira Souza", "joanasouza", "CLIENTE-A")
    assert sol["confirmado_em"] and conv.banco.consentimento(conv.sid)["email_confirmado_em"]
    assert _acoes(conv)[-1] == ("convite", "convite_alterado", "campos: nome; uid do convite: joanalima")
    assert conv.correio.enviados[-1]["para"] == "admin@teste.local"
    assert conv.client.get(conv.link).status_code == 410


def test_aceitar_mudando_o_cpf_nao_grava_o_cpf_no_historico(conv):
    assert _aceitar(conv, cpf="987.654.321-00").status_code == 200
    sol = conv.banco.obter(conv.sid)
    assert (sol["status"], sol["cpf"], sol["uid_sugerido"]) == ("pendente", "98765432100", "joanalima")
    detalhe = _acoes(conv)[-1][2]
    assert detalhe == "campos: cpf; uid do convite: joanalima"
    assert all("98765432100" not in (h["detalhe"] or "") and "12345678909" not in (h["detalhe"] or "")
               for h in auditoria(conv.banco))


def test_aceitar_mudando_o_email_exige_confirmar_o_novo(conv):
    r = _aceitar(conv, email="Joana.Nova@Exemplo.org")
    assert r.status_code == 200 and "joanalima" not in conv.dir.contas
    sol = conv.banco.obter(conv.sid)
    assert (sol["status"], sol["email"], sol["confirmado_em"]) == \
           ("aguardando_confirmacao", "joana.nova@exemplo.org", None)
    assert conv.banco.consentimento(conv.sid)["email_confirmado_em"] is None
    assert _acoes(conv)[-1] == ("convite", "convite_alterado", "campos: email; uid do convite: joanalima")
    assert conv.correio.enviados[-1]["para"] == "joana.nova@exemplo.org"
    assert conv.client.get(conv.link).status_code == 410
    assert conv.client.post(conv.correio.caminho_do_link()).status_code == 200  # confirma o e-mail novo
    assert conv.banco.obter(conv.sid)["status"] == "pendente"
    assert conv.banco.consentimento(conv.sid)["email_confirmado_em"]


def test_aceitar_mudando_o_email_com_smtp_fora_nao_tem_efeito(conv):
    conv.correio.falhar = True
    assert _aceitar(conv, email="joana.nova@exemplo.org").status_code == 503
    assert conv.banco.obter(conv.sid)["status"] == "convidado" and conv.banco.consentimento(conv.sid) is None
    conv.correio.falhar = False
    assert conv.client.get(conv.link).status_code == 200


def test_aceitar_com_ldap_fora_mantem_o_convite(conv):
    conv.dir.falhar_criacao = True
    r = _aceitar(conv)
    assert r.status_code == 503 and "indisponível" in r.text
    assert conv.banco.obter(conv.sid)["status"] == "convidado" and conv.banco.consentimento(conv.sid) is None
    assert _acoes(conv)[-1][:2] == ("convite", "erro_ldap")
    conv.dir.falhar_criacao = False
    assert conv.client.get(conv.link).status_code == 200
    assert _aceitar(conv).status_code == 302 and "joanalima" in conv.dir.contas


def test_link_de_convite_usado_cancelado_ou_expirado(conv):
    _aceitar(conv)
    assert conv.client.get(conv.link).status_code == 410
    assert _aceitar(conv).status_code == 410
    # cancelado
    _login(conv)
    conv.client.post("/admin/convidar", data={**CONVITE, "cpf": "987.654.321-00", "email": "b@exemplo.org",
                                              "uid": "joanab"})
    link = conv.correio.caminho_do_link()
    [sol] = conv.banco.buscar("", "convidado", 1)
    conv.client.post(f"/admin/solicitacao/{sol['id']}/cancelar-convite")
    assert conv.client.get(link).status_code == 410
    # expirado
    conv.client.post("/admin/convidar", data={**CONVITE, "cpf": "390.533.447-05", "email": "c@exemplo.org",
                                              "uid": "joanac"})
    link = conv.correio.caminho_do_link()
    conv.relogio.avancar(days=7)
    assert conv.client.get(link).status_code == 410
    assert conv.client.post(link, data={**ACEITE, "cpf": "390.533.447-05", "email": "c@exemplo.org"}).status_code \
        == 410


def test_aceitar_respeita_limite_de_token(conv):
    for _ in range(10):
        _aceitar(conv, consentimento="")
    assert _aceitar(conv).status_code == 429


def test_revisao_do_formulario_formata_cpf_e_telefone(amb):
    r = amb.client.post("/cadastro", data=FORM)
    assert "529.982.247-25" in r.text and "+55 (11) 91234-5678" in r.text


def _tokens_confirmacao_validos(amb, sid):
    import sqlite3
    with sqlite3.connect(amb.banco.caminho) as con:
        return con.execute("SELECT COUNT(*) FROM tokens WHERE finalidade='confirmar_email' AND alvo=? "
                           "AND usado_em IS NULL", (f"sol:{sid}",)).fetchone()[0]


def test_aceite_que_perde_a_corrida_nao_deixa_token_de_confirmacao(conv, monkeypatch):
    monkeypatch.setattr(conv.banco, "aceitar_convite", lambda *a, **kw: False)  # outro pedido venceu
    assert _aceitar(conv, email="atacante@exemplo.org").status_code == 410
    assert _tokens_confirmacao_validos(conv, conv.sid) == 0
    assert [e["para"] for e in conv.correio.enviados] == ["joana@exemplo.org"]  # só o convite


def test_aceitar_mudando_o_email_com_smtp_fora_restaura_o_convite(conv):
    conv.correio.falhar = True
    assert _aceitar(conv, nome="Joana Pereira Souza", email="joana.nova@exemplo.org").status_code == 503
    sol = conv.banco.obter(conv.sid)
    assert (sol["status"], sol["nome"], sol["email"], sol["uid_sugerido"], sol["confirmado_em"]) == \
           ("convidado", "Joana Pereira Lima", "joana@exemplo.org", "joanalima", None)
    assert _tokens_confirmacao_validos(conv, conv.sid) == 0
    conv.correio.falhar = False
    assert 'value="joana@exemplo.org"' in conv.client.get(conv.link).text


def test_dois_aceites_simultaneos_sem_mudancas_criam_uma_conta_com_os_dados_de_quem_venceu(conv, monkeypatch):
    real = conv.banco.aceitar_convite
    respostas = []

    def concorrente(*a, **kw):
        ok = real(*a, **kw)
        if not respostas:  # o outro pedido chega logo depois da gravação do primeiro
            respostas.append(_aceitar(conv, telefone="(21) 99999-0000"))
        return ok

    monkeypatch.setattr(conv.banco, "aceitar_convite", concorrente)
    primeiro = _aceitar(conv, telefone="(11) 98765-4321")
    assert primeiro.status_code == 302 and respostas[0].status_code == 410
    assert list(conv.dir.contas) == ["existente", "joanalima"]
    assert conv.dir.contas["joanalima"]["telefone"] == "+5511987654321"


def test_aceite_com_mudancas_expira_solicitacoes_anteriores_do_cpf(conv):
    from tests.unit.test_publico import _solicitar
    _solicitar(conv)  # solicitação do formulário com o CPF 529.982.247-25
    [antiga] = conv.banco.buscar("", "aguardando_confirmacao", 1)
    assert _aceitar(conv, cpf="529.982.247-25").status_code == 200
    assert conv.banco.obter(antiga["id"])["status"] == "expirada"
    assert conv.banco.obter(conv.sid)["status"] == "pendente"


def test_aceite_com_email_novo_grava_o_consentimento_antes_de_enviar(conv, monkeypatch):
    enviar = conv.correio.enviar
    vistos = []

    def espiar(para, *a):
        vistos.append(conv.banco.consentimento(conv.sid))
        enviar(para, *a)

    monkeypatch.setattr(conv.correio, "enviar", espiar)
    assert _aceitar(conv, email="joana.nova@exemplo.org").status_code == 200
    assert vistos and vistos[-1] is not None and vistos[-1]["email_confirmado_em"] is None
