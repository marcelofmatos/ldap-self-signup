from datetime import datetime, timedelta, timezone

import pytest

from app.banco import Banco
from tests.fakes import auditoria, texto_aviso

AGORA = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)
DADOS = {"nome": "Maria da Silva Souza", "cpf": "52998224725", "email": "maria@exemplo.org",
         "telefone": "+5511912345678", "justificativa": "Equipe de regulação."}


@pytest.fixture
def banco(tmp_path):
    return Banco(tmp_path / "t.db")


def _criar(banco, dados=DADOS, agora=AGORA):
    return banco.criar_solicitacao(dados, uid_sugerido="mariasouza", ip="10.0.0.1", user_agent="UA",
                                   versao_aviso="v1hash", texto_aviso="# Aviso", agora=agora)


def test_criar_solicitacao_e_consentimento(banco):
    sid = _criar(banco)
    sol = banco.obter(sid)
    assert sol["status"] == "aguardando_confirmacao"
    assert sol["uid_sugerido"] == "mariasouza" and sol["cpf"] == "52998224725"
    assert sol["criado_em"] == "2026-11-04T12:00:00+00:00" and sol["link_enviado"] == 0
    c = banco.consentimento(sid)
    assert c["versao_aviso"] == "v1hash" and c["ip"] == "10.0.0.1" and c["email_confirmado_em"] is None
    assert texto_aviso(banco, "v1hash") == "# Aviso"


def test_nova_solicitacao_mesmo_cpf_e_email_expira_anterior(banco):
    s1 = _criar(banco)
    s2 = _criar(banco)
    outro = _criar(banco, {**DADOS, "email": "outro@exemplo.org"})
    assert banco.obter(s1)["status"] == "aguardando_confirmacao"
    banco.expirar_anteriores(DADOS["cpf"], DADOS["email"], s2)
    assert banco.obter(s1)["status"] == "expirada"
    assert banco.obter(s2)["status"] == "aguardando_confirmacao"
    assert banco.obter(outro)["status"] == "aguardando_confirmacao"


def test_confirmar_email(banco):
    sid = _criar(banco)
    assert banco.confirmar_email(sid, AGORA) is True
    assert banco.obter(sid)["status"] == "pendente"
    assert banco.consentimento(sid)["email_confirmado_em"] == "2026-11-04T12:00:00+00:00"
    assert banco.confirmar_email(sid, AGORA) is False


def test_buscar_e_atualizar(banco):
    sid = _criar(banco)
    banco.confirmar_email(sid, AGORA)
    assert [s["id"] for s in banco.buscar("", "pendente", 1)] == [sid]
    banco.atualizar(sid, status="aprovada", uid_final="mariasouza", organizacao="CLIENTE-A", link_enviado=1)
    assert banco.buscar("", "pendente", 1) == []
    assert banco.obter(sid)["organizacao"] == "CLIENTE-A"


def test_atualizar_rejeita_campo_desconhecido(banco):
    sid = _criar(banco)
    with pytest.raises(ValueError):
        banco.atualizar(sid, cpf="x")


def test_rejeitar_so_se_pendente(banco):
    sid = _criar(banco)
    assert banco.rejeitar(sid, "x", "chefe", "2026-11-04T12:00:00+00:00") is False  # aguardando confirmação
    banco.confirmar_email(sid, AGORA)
    assert banco.rejeitar(sid, "fora do escopo", "chefe", "2026-11-04T12:00:00+00:00") is True
    sol = banco.obter(sid)
    assert (sol["status"], sol["motivo"], sol["decidido_por"], sol["decidido_em"]) == \
           ("rejeitada", "fora do escopo", "chefe", "2026-11-04T12:00:00+00:00")
    assert banco.rejeitar(sid, "de novo", "chefe", "2026-11-04T12:00:00+00:00") is False


def test_destravar_so_se_aprovando(banco):
    sid = _criar(banco)
    banco.confirmar_email(sid, AGORA)
    assert banco.destravar(sid) is False
    banco.reivindicar(sid)
    assert banco.destravar(sid) is True and banco.obter(sid)["status"] == "pendente"


def test_remover_solicitacao(banco):
    sid = _criar(banco)
    banco.inserir_token("h1", "confirmar_email", f"sol:{sid}", "2026-11-05T12:00:00+00:00")
    banco.remover_solicitacao(sid)
    assert banco.obter(sid) is None and banco.obter_token("h1") is None


def test_expirar_aguardando(banco):
    sid = _criar(banco)
    banco.expirar_aguardando(AGORA + timedelta(hours=1))
    assert banco.obter(sid)["status"] == "expirada"


def test_tokens(banco):
    banco.inserir_token("h1", "definir_senha", "mariasouza", "2026-11-05T12:00:00+00:00")
    assert banco.obter_token("h1")["alvo"] == "mariasouza"
    assert banco.marcar_token_usado("h1", AGORA) is True
    assert banco.marcar_token_usado("h1", AGORA) is False
    banco.inserir_token("h2", "definir_senha", "mariasouza", "2026-11-05T12:00:00+00:00")
    banco.invalidar_tokens("definir_senha", "mariasouza", AGORA)
    assert banco.obter_token("h2")["usado_em"] is not None


def test_auditoria(banco):
    banco.auditar("chefe", "aprovar", "sol:1", "uid=x", AGORA)
    assert auditoria(banco)[0]["acao"] == "aprovar"


def test_ok(banco):
    assert banco.ok() is True


def test_historico_da_solicitacao_em_ordem(banco):
    banco.auditar("publico", "solicitacao_criada", "sol:1", "", AGORA)
    banco.auditar("chefe", "erro_ldap", "sol:1", "uid=x org=Y: falhou", AGORA + timedelta(minutes=1))
    banco.auditar("chefe", "aprovar", "sol:2", "", AGORA)
    banco.auditar("x", "senha_definida", "x", "", AGORA)
    assert [h["acao"] for h in banco.historico(1)] == ["solicitacao_criada", "erro_ldap"]
    assert banco.historico(1)[1]["detalhe"] == "uid=x org=Y: falhou"


def test_solicitacao_aprovada_do_uid(banco):
    s1 = _criar(banco)
    s2 = _criar(banco)
    assert banco.solicitacao_aprovada_do_uid("mariasouza") is None
    banco.atualizar(s1, status="aprovada", uid_final="mariasouza")
    banco.atualizar(s2, status="rejeitada", uid_final="mariasouza")
    assert banco.solicitacao_aprovada_do_uid("mariasouza") == s1


def _muitas(banco, n):
    ids = []
    for i in range(n):
        dados = {**DADOS, "nome": f"Pessoa {i:02d}", "cpf": f"{i:011d}", "email": f"p{i}@exemplo.org",
                 "justificativa": f"motivo {i}"}
        sid = _criar(banco, dados)
        banco.confirmar_email(sid, AGORA)
        ids.append(sid)
    return ids


def test_buscar_pagina(banco):
    ids = _muitas(banco, 60)
    paginas = [banco.buscar("", None, p) for p in (1, 2, 3)]
    assert [len(r) for r in paginas] == [25, 25, 10] and banco.contar_por_status("") == {"pendente": 60}
    assert paginas[0][0]["id"] == ids[-1] and paginas[2][-1]["id"] == ids[0]


def test_buscar_por_campos(banco):
    _criar(banco, {**DADOS, "nome": "Outro Fulano", "cpf": "11144477735", "email": "outro@x.org",
                   "justificativa": "Time de vigilância"})
    alvo = _criar(banco)
    for termo in ("529.982", "52998", "MARIA@exemplo", "silva souza", "regulação", "mariasouza", "aguardando"):
        rows = banco.buscar(termo, None, 1)
        assert alvo in [r["id"] for r in rows], termo
    assert [r["id"] for r in banco.buscar("529.982", None, 1)] == [alvo]


def test_buscar_curingas_sao_literais(banco):
    _criar(banco)
    assert banco.buscar("%", None, 1) == []
    assert banco.buscar("m_ria", None, 1) == []
    _criar(banco, {**DADOS, "justificativa": "100% remoto"})
    assert len(banco.buscar("100%", None, 1)) == 1


def test_buscar_filtra_status_e_conta(banco):
    a, b = _criar(banco), _criar(banco)
    banco.confirmar_email(a, AGORA)
    assert [r["id"] for r in banco.buscar("", "pendente", 1)] == [a]
    assert len(banco.buscar("", "aguardando_confirmacao", 1)) == 1
    assert banco.contar_por_status("") == {"pendente": 1, "aguardando_confirmacao": 1}
    assert banco.contar_por_status("nada-disso") == {}


def test_buscar_digitos_so_para_termo_de_cpf_ou_telefone(banco):
    so_cpf = _criar(banco, {**DADOS, "nome": "Ana", "email": "ana@x.org", "cpf": "22222222222",
                            "telefone": "+5511900000000", "justificativa": "j"})
    assert so_cpf not in [r["id"] for r in banco.buscar("x2@", None, 1)]
    alvo = _criar(banco)
    assert [r["id"] for r in banco.buscar("(11) 91234-5678", None, 1)] == [alvo]
    assert [r["id"] for r in banco.buscar("529.982", None, 1)] == [alvo]


def test_indices_de_historico_e_lista(banco):
    import sqlite3
    with sqlite3.connect(banco.caminho) as con:
        colunas = {(t, r[2]) for t in ("auditoria", "solicitacoes")
                   for (nome,) in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?", (t,))
                   for r in con.execute(f"PRAGMA index_info('{nome}')")}
    assert {("auditoria", "alvo"), ("solicitacoes", "status"), ("solicitacoes", "uid_final")} <= colunas


# --- v0.4: convites ---
SCHEMA_V03 = """
CREATE TABLE solicitacoes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nome TEXT NOT NULL, cpf TEXT NOT NULL, email TEXT NOT NULL, telefone TEXT NOT NULL,
  justificativa TEXT NOT NULL, ip TEXT, user_agent TEXT,
  status TEXT NOT NULL, uid_sugerido TEXT NOT NULL, uid_final TEXT, organizacao TEXT,
  decidido_por TEXT, motivo TEXT,
  criado_em TEXT NOT NULL, confirmado_em TEXT, decidido_em TEXT,
  link_enviado INTEGER NOT NULL DEFAULT 0
);
INSERT INTO solicitacoes (nome, cpf, email, telefone, justificativa, status, uid_sugerido, criado_em)
VALUES ('Antiga Pessoa', '52998224725', 'a@exemplo.org', '+5511912345678', 'antiga', 'pendente', 'antigapessoa',
        '2026-11-01T12:00:00+00:00');
"""

CONVIDADA = {"nome": "Joana Pereira Lima", "cpf": "12345678909", "email": "joana@exemplo.org",
             "telefone": "+5511987654321"}


def _convite(banco, dados=CONVIDADA, agora=AGORA):
    return banco.criar_convite(dados, uid="joanalima", organizacao="CLIENTE-A", convidado_por="chefe", agora=agora)


def test_migracao_do_banco_v03_adiciona_origem_e_convidado_por(tmp_path):
    import sqlite3
    caminho = tmp_path / "antigo.db"
    with sqlite3.connect(caminho) as con:
        con.executescript(SCHEMA_V03)
    banco = Banco(caminho)
    sol = banco.obter(1)
    assert sol["origem"] == "formulario" and sol["convidado_por"] is None and sol["nome"] == "Antiga Pessoa"
    Banco(caminho)  # reabrir não migra de novo
    assert _convite(banco) == 2


def test_solicitacao_do_formulario_tem_origem_formulario(banco):
    sol = banco.obter(_criar(banco))
    assert sol["origem"] == "formulario" and sol["convidado_por"] is None


def test_criar_convite(banco):
    sid = _convite(banco)
    sol = banco.obter(sid)
    assert (sol["status"], sol["origem"], sol["convidado_por"], sol["uid_sugerido"], sol["organizacao"]) == \
           ("convidado", "convite", "chefe", "joanalima", "CLIENTE-A")
    assert sol["justificativa"] == "" and sol["link_enviado"] == 0 and banco.consentimento(sid) is None


def test_busca_acha_convite_por_quem_convidou(banco):
    sid = _convite(banco)
    assert [s["id"] for s in banco.buscar("chefe", None, 1)] == [sid]


def test_expirar_convites_do_cpf_invalida_tokens(banco):
    sid = _convite(banco)
    banco.inserir_token("h1", "convite", f"sol:{sid}", "2026-12-01T00:00:00+00:00")
    pendente = _criar(banco, {**DADOS, "cpf": CONVIDADA["cpf"]})
    assert banco.expirar_convites_do_cpf(CONVIDADA["cpf"], AGORA) == [sid]
    assert banco.obter(sid)["status"] == "expirada" and banco.obter_token("h1")["usado_em"]
    assert banco.obter(pendente)["status"] == "aguardando_confirmacao"
    assert banco.expirar_convites_do_cpf(CONVIDADA["cpf"], AGORA) == []


def test_cancelar_convite_so_se_convidado(banco):
    sid = _convite(banco)
    banco.inserir_token("h1", "convite", f"sol:{sid}", "2026-12-01T00:00:00+00:00")
    assert banco.cancelar_convite(sid, AGORA) is True
    assert banco.obter(sid)["status"] == "expirada" and banco.obter_token("h1")["usado_em"]
    assert banco.cancelar_convite(sid, AGORA) is False
    assert banco.cancelar_convite(_criar(banco), AGORA) is False


def test_aceitar_convite_atualiza_dados_so_se_convidado(banco):
    sid = _convite(banco)
    novos = {**CONVIDADA, "nome": "Joana Pereira Souza", "justificativa": "Equipe nova."}
    assert banco.aceitar_convite(sid, novos, ip="10.0.0.2", user_agent="UA2", uid_sugerido="joanasouza",
                                 status="pendente", confirmado_em="2026-11-04T12:00:00+00:00") is True
    sol = banco.obter(sid)
    assert (sol["nome"], sol["uid_sugerido"], sol["status"], sol["ip"], sol["justificativa"], sol["confirmado_em"]) \
        == ("Joana Pereira Souza", "joanasouza", "pendente", "10.0.0.2", "Equipe nova.", "2026-11-04T12:00:00+00:00")
    assert banco.aceitar_convite(sid, novos, ip="x", user_agent="x", uid_sugerido="x", status="pendente") is False


def test_registrar_consentimento(banco):
    sid = _convite(banco)
    banco.registrar_consentimento(sid, versao_aviso="v2", texto_aviso="# Aviso 2", ip="10.0.0.2", user_agent="UA",
                                  agora=AGORA, email_confirmado=True)
    c = banco.consentimento(sid)
    assert (c["versao_aviso"], c["ip"], c["aceito_em"], c["email_confirmado_em"]) == \
           ("v2", "10.0.0.2", "2026-11-04T12:00:00+00:00", "2026-11-04T12:00:00+00:00")
    assert texto_aviso(banco, "v2") == "# Aviso 2"
    outro = _convite(banco, {**CONVIDADA, "cpf": "98765432100"})
    banco.registrar_consentimento(outro, versao_aviso="v2", texto_aviso="# Aviso 2", ip="", user_agent="",
                                  agora=AGORA, email_confirmado=False)
    assert banco.consentimento(outro)["email_confirmado_em"] is None


def test_reivindicar_so_pendente(banco):
    sid = _convite(banco)
    assert banco.reivindicar(sid) is False  # convite não é reivindicado: o aceite grava e reivindica junto
    assert banco.obter(sid)["status"] == "convidado"


CONSENTIMENTO = dict(versao_aviso="v1", texto_aviso="t", ip="10.0.0.2", user_agent="UA", agora=AGORA,
                     email_confirmado=False)


def test_aceitar_convite_grava_o_consentimento_no_mesmo_passo(banco):
    sid = _convite(banco)
    assert banco.aceitar_convite(sid, {**CONVIDADA, "justificativa": ""}, ip="", user_agent="",
                                 uid_sugerido="joanalima", status="aguardando_confirmacao",
                                 consentimento=CONSENTIMENTO) is True
    c = banco.consentimento(sid)
    assert (c["versao_aviso"], c["ip"], c["aceito_em"], c["email_confirmado_em"]) == \
           ("v1", "10.0.0.2", "2026-11-04T12:00:00+00:00", None)
    # perdeu a corrida: nenhum consentimento a mais
    assert banco.aceitar_convite(sid, {**CONVIDADA, "justificativa": ""}, ip="", user_agent="", uid_sugerido="x",
                                 status="pendente", consentimento=CONSENTIMENTO) is False
    with banco._con() as con:
        assert con.execute("SELECT COUNT(*) FROM consentimentos WHERE solicitacao_id=?", (sid,)).fetchone()[0] == 1


def test_devolver_convite_remove_o_consentimento_do_aceite(banco):
    sid = _convite(banco)
    original = banco.obter(sid)
    banco.aceitar_convite(sid, {**CONVIDADA, "email": "nova@exemplo.org", "justificativa": ""}, ip="",
                          user_agent="", uid_sugerido="joanalima", status="aguardando_confirmacao",
                          consentimento=CONSENTIMENTO)
    assert banco.devolver_convite(original) is True and banco.consentimento(sid) is None


def test_expirar_aguardando_nao_expira_convite_aceito_sem_consentimento_gravado(banco):
    sid = _convite(banco, agora=AGORA - timedelta(days=5))
    banco.aceitar_convite(sid, {**CONVIDADA, "justificativa": ""}, ip="", user_agent="", uid_sugerido="joanalima",
                          status="aguardando_confirmacao")
    banco.expirar_aguardando(AGORA - timedelta(hours=1))
    assert banco.obter(sid)["status"] == "aguardando_confirmacao"


def test_expirar_aguardando_conta_do_aceite_do_convite(banco):
    sid = _convite(banco, agora=AGORA - timedelta(days=5))
    banco.aceitar_convite(sid, {**CONVIDADA, "justificativa": ""}, ip="", user_agent="", uid_sugerido="joanalima",
                          status="aguardando_confirmacao")
    banco.registrar_consentimento(sid, versao_aviso="v1", texto_aviso="t", ip="", user_agent="", agora=AGORA,
                                  email_confirmado=False)
    banco.expirar_aguardando(AGORA - timedelta(hours=1))
    assert banco.obter(sid)["status"] == "aguardando_confirmacao"
    banco.expirar_aguardando(AGORA + timedelta(hours=1))
    assert banco.obter(sid)["status"] == "expirada"


def test_devolver_convite_so_se_aguardando(banco):
    sid = _convite(banco)
    original = banco.obter(sid)
    banco.aceitar_convite(sid, {**CONVIDADA, "email": "nova@exemplo.org", "justificativa": "x"}, ip="1",
                          user_agent="u", uid_sugerido="outro", status="aguardando_confirmacao")
    assert banco.devolver_convite(original) is True
    sol = banco.obter(sid)
    assert (sol["status"], sol["email"], sol["uid_sugerido"], sol["justificativa"]) == \
           ("convidado", "joana@exemplo.org", "joanalima", "")
    assert banco.devolver_convite(original) is False


def test_convite_aberto_com_uid(banco):
    sid = _convite(banco)
    assert banco.convite_aberto_com_uid("joanalima", exceto_cpf="98765432100") == sid
    assert banco.convite_aberto_com_uid("joanalima", exceto_cpf=CONVIDADA["cpf"]) is None
    assert banco.convite_aberto_com_uid("outro", exceto_cpf="98765432100") is None
    banco.cancelar_convite(sid, AGORA)
    assert banco.convite_aberto_com_uid("joanalima", exceto_cpf="98765432100") is None


def test_lotes_por_admin_com_expiracao(banco):
    linhas = [{"linha": 2, "nome": "Ana Costa", "cpf": "52998224725", "email": "a@exemplo.org", "telefone": ""}]
    lid = banco.criar_lote("chefe", linhas, AGORA, expira_antes=AGORA - timedelta(hours=1))
    assert banco.obter_lote(lid, "chefe", AGORA - timedelta(hours=1)) == linhas
    assert banco.obter_lote(lid, "outro", AGORA - timedelta(hours=1)) is None
    velho = banco.criar_lote("chefe", linhas, AGORA - timedelta(hours=2), expira_antes=AGORA - timedelta(hours=3))
    banco.obter_lote(lid, "chefe", AGORA - timedelta(hours=1))  # limpa as expiradas
    assert banco.remover_lote(velho) is False
    assert banco.remover_lote(lid) is True and banco.remover_lote(lid) is False


def test_criar_lote_apaga_as_previas_expiradas(banco):
    velho = banco.criar_lote("chefe", [], AGORA - timedelta(hours=2), expira_antes=AGORA - timedelta(hours=3))
    banco.criar_lote("chefe", [], AGORA, expira_antes=AGORA - timedelta(hours=1))
    assert banco.remover_lote(velho) is False


def test_limpar_lotes(banco):
    velho = banco.criar_lote("chefe", [], AGORA - timedelta(hours=2), expira_antes=AGORA - timedelta(hours=3))
    novo = banco.criar_lote("chefe", [], AGORA, expira_antes=AGORA - timedelta(hours=3))
    banco.limpar_lotes(AGORA - timedelta(hours=1))
    assert banco.remover_lote(velho) is False and banco.remover_lote(novo) is True


def test_criar_alteracao_pendente_com_consentimento_e_expira_a_anterior(banco):
    agora = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    dados = {"nome": "Maria Souza", "cpf": "52998224725", "email": "m@x.org", "telefone": "+5511912345678",
             "justificativa": ""}
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua", agora=agora,
                email_confirmado=False)
    s1 = banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons)
    s2 = banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons)
    sol = banco.obter(s2)
    assert sol["status"] == "pendente" and sol["origem"] == "alteracao"
    assert sol["uid_sugerido"] == "mariasouza" and sol["organizacao"] == "CLIENTE-A" and sol["ip"] == "1.2.3.4"
    assert banco.consentimento(s2)["versao_aviso"] == "v1"
    assert banco.obter(s1)["status"] == "expirada"


def test_expirar_anteriores_nao_toca_alteracao(banco):
    dados = {"nome": "Maria Souza", "cpf": "52998224725", "email": "m@x.org", "telefone": "+5511912345678",
             "justificativa": ""}
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua", agora=AGORA,
                email_confirmado=False)
    alt = banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons)
    outra = _criar(banco)
    banco.expirar_anteriores("52998224725", DADOS["email"], outra + 1)
    assert banco.obter(alt)["status"] == "pendente"
    assert banco.obter(outra)["status"] == "expirada"


def test_criar_alteracao_aguardando_e_expira_a_anterior_aguardando(banco):
    agora = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    dados = {"nome": "Maria Souza", "cpf": "52998224725", "email": "n@x.org", "telefone": "+5511912345678",
             "justificativa": ""}
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua", agora=agora,
                email_confirmado=False)
    s1 = banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons, aguardando=True)
    assert banco.obter(s1)["status"] == "aguardando_confirmacao"
    s2 = banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons)
    assert banco.obter(s1)["status"] == "expirada" and banco.obter(s2)["status"] == "pendente"


def test_expirar_aguardando_expira_alteracao_apos_o_limite(banco):
    agora = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
    dados = {"nome": "Maria Souza", "cpf": "52998224725", "email": "n@x.org", "telefone": "+5511912345678",
             "justificativa": ""}
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua", agora=agora,
                email_confirmado=False)
    sid = banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons, aguardando=True)
    banco.expirar_aguardando(agora - timedelta(hours=1))
    assert banco.obter(sid)["status"] == "aguardando_confirmacao"
    banco.expirar_aguardando(agora + timedelta(hours=1))
    assert banco.obter(sid)["status"] == "expirada"


def _alteracao(banco, aguardando=False):
    dados = {"nome": "Maria Souza", "cpf": "52998224725", "email": "n@x.org", "telefone": "+5511912345678",
             "justificativa": ""}
    cons = dict(versao_aviso="v1", texto_aviso="aviso", ip="1.2.3.4", user_agent="ua", agora=AGORA,
                email_confirmado=False)
    return banco.criar_alteracao(dados, uid="mariasouza", organizacao="CLIENTE-A", consentimento=cons,
                                 aguardando=aguardando)


def test_alteracao_em_aberto_sem_alteracao_e_none(banco):
    assert banco.alteracao_em_aberto("mariasouza") is None


def test_alteracao_em_aberto_pendente_e_aguardando(banco):
    sid = _alteracao(banco)
    assert banco.alteracao_em_aberto("mariasouza") == {"id": sid, "status": "pendente"}
    assert banco.alteracao_em_aberto("outra") is None
    sid2 = _alteracao(banco, aguardando=True)
    assert banco.alteracao_em_aberto("mariasouza") == {"id": sid2, "status": "aguardando_confirmacao"}


def test_alteracao_em_aberto_aprovando(banco):
    sid = _alteracao(banco)
    with banco._con() as con:
        con.execute("UPDATE solicitacoes SET status='aprovando' WHERE id=?", (sid,))
    assert banco.alteracao_em_aberto("mariasouza") == {"id": sid, "status": "aprovando"}


@pytest.mark.parametrize("status", ["rejeitada", "aprovada", "expirada"])
def test_alteracao_em_aberto_decidida_e_none(banco, status):
    sid = _alteracao(banco)
    with banco._con() as con:
        con.execute("UPDATE solicitacoes SET status=? WHERE id=?", (status, sid))
    assert banco.alteracao_em_aberto("mariasouza") is None


def test_criar_convite_email(banco):
    sid = banco.criar_convite_email("ana@exemplo.org", organizacao="CLIENTE-A", convidado_por="chefe", agora=AGORA)
    sol = banco.obter(sid)
    assert (sol["status"], sol["origem"], sol["email"], sol["organizacao"], sol["convidado_por"]) == \
           ("convidado", "convite_email", "ana@exemplo.org", "CLIENTE-A", "chefe")
    for campo in ("nome", "cpf", "telefone", "justificativa", "uid_sugerido"):
        assert sol[campo] == "", campo


def test_expirar_convites_do_email_e_convite_aberto(banco):
    sid = banco.criar_convite_email("ana@exemplo.org", organizacao="CLIENTE-A", convidado_por="chefe", agora=AGORA)
    outro = banco.criar_convite_email("bia@exemplo.org", organizacao="CLIENTE-A", convidado_por="chefe", agora=AGORA)
    banco.inserir_token("h1", "convite", f"sol:{sid}", "2026-12-01T00:00:00+00:00")
    assert banco.convite_email_aberto("ana@exemplo.org") == sid
    assert banco.convite_email_aberto("zed@exemplo.org") is None
    assert banco.expirar_convites_do_email("ana@exemplo.org", AGORA) == [sid]
    assert banco.obter(sid)["status"] == "expirada" and banco.obter_token("h1")["usado_em"]
    assert banco.obter(outro)["status"] == "convidado"
    assert banco.convite_email_aberto("ana@exemplo.org") is None
    assert banco.expirar_convites_do_email("ana@exemplo.org", AGORA) == []


def test_expirar_convites_do_cpf_nao_pega_convite_por_email(banco):
    sid = banco.criar_convite_email("ana@exemplo.org", organizacao="CLIENTE-A", convidado_por="chefe", agora=AGORA)
    assert banco.expirar_convites_do_cpf("", AGORA) == []
    assert banco.obter(sid)["status"] == "convidado"
