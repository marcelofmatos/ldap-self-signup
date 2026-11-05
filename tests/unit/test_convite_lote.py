import re
from io import BytesIO

import pytest

from tests.fakes import auditoria
from tests.unit.test_admin import _login
from tests.unit.test_lote import xlsx

CABECALHO = ("Nome", "CPF", "E-mail", "Telefone")
# pessoas fictícias; CPFs válidos gerados para teste
SEIS = [
    ("Ana Beatriz Costa", 52998224725.0, "ana@exemplo.org", "(11) 91234-5678"),
    ("Bruno Dias Melo", "111.444.777-35", "bruno@exemplo.org", ""),
    ("Carla Nunes Rocha \n", "52601815906.0", "carla@exemplo.org", "11 98888-7777"),
    ("Davi Souza Prado", 8301661305, "davi@exemplo.org", None),
    ("Elisa Gomes Teles", "18609139034", "elisa@exemplo.org", "21987654321"),  # já existe no LDAP (CPF)
    ("Fabio Ramos Leal", "123.456.789-00", "fabio@exemplo.org", "21987654321"),  # CPF inválido
]


@pytest.fixture
def adm(amb):
    amb.dir.contas["elisa"] = dict(uid="elisa", cn="Elisa Teles", mail="elisa.antiga@exemplo.org", ou="CLIENTE-A",
                                   cpf="18609139034", telefone="", senha=None)
    _login(amb)
    return amb


def _enviar_planilha(amb, conteudo, nome="pessoas.xlsx"):
    return amb.client.post("/admin/convidar/lote", data={"planilha": (BytesIO(conteudo), nome)},
                           content_type="multipart/form-data")


def _previa(amb, linhas=SEIS):
    r = _enviar_planilha(amb, xlsx(CABECALHO, *linhas))
    assert r.status_code == 302, r.text
    return r.headers["Location"]


def _caixas(html):
    """Checkboxes 'enviar' da prévia: índice -> (marcado, desabilitado)."""
    caixas = {}
    for tag in re.findall(r'<input[^>]*name="enviar_\d+"[^>]*>', html):
        i = int(re.search(r'name="enviar_(\d+)"', tag).group(1))
        caixas[i] = (" checked" in tag, " disabled" in tag)
    return caixas


def _convidados(amb):
    return amb.banco.buscar("", "convidado", 1, 100)


def _lotes(amb):
    with amb.banco._con() as con:
        return con.execute("SELECT COUNT(*) FROM lotes").fetchone()[0]


def test_lote_exige_login(amb):
    for r in (amb.client.get("/admin/convidar/lote"), amb.client.post("/admin/convidar/lote"),
              amb.client.get("/admin/convidar/lote/1"), amb.client.post("/admin/convidar/lote/1")):
        assert r.status_code == 302 and "/admin/login" in r.headers["Location"]


def test_pagina_de_upload_e_link_no_convidar(adm):
    assert 'href="/admin/convidar/lote"' in adm.client.get("/admin/convidar").text
    r = adm.client.get("/admin/convidar/lote")
    assert r.status_code == 200 and 'type="file"' in r.text and 'name="planilha"' in r.text
    assert 'enctype="multipart/form-data"' in r.text


@pytest.mark.parametrize("nome, conteudo", [("p.pdf", b"%PDF"), ("p.xlsx", b"corrompido")])
def test_upload_invalido(adm, nome, conteudo):
    r = _enviar_planilha(adm, conteudo, nome)
    assert r.status_code == 400 and 'class="erro"' in r.text and _lotes(adm) == 0


def test_upload_sem_arquivo(adm):
    r = adm.client.post("/admin/convidar/lote", data={}, content_type="multipart/form-data")
    assert r.status_code == 400 and _lotes(adm) == 0


def test_upload_maior_que_o_limite(adm):
    r = _enviar_planilha(adm, b"a" * (1024 * 1024 + 10), "p.csv")
    assert r.status_code == 400 and "1 MB" in r.text and _lotes(adm) == 0


def test_previa_mostra_dados_normalizados_uid_erros_e_conflitos(adm):
    r = adm.client.get(_previa(adm))
    assert r.status_code == 200
    html = r.text
    assert "529.982.247-25" in html and "+55 (11) 91234-5678" in html and "083.016.613-05" in html
    assert 'value="anacosta"' in html and 'value="carlarocha"' in html  # uid sugerido, editável
    assert "Carla Nunes Rocha" in html and "Carla Nunes Rocha \n" not in html
    assert "CPF inválido" in html and "CPF na conta elisa" in html
    assert 'name="outra_pessoa_4"' in html and 'name="outra_pessoa_0"' not in html
    assert _caixas(html) == {0: (True, False), 1: (True, False), 2: (True, False), 3: (True, False),
                             4: (False, False), 5: (False, True)}
    assert "<option>CLIENTE-A</option>" in html and 'value="__nova__"' in html


def test_previa_uid_em_uso_ou_reservado_por_convite(adm):
    adm.dir.contas["anacosta"] = dict(uid="anacosta", cn="Outra Ana", mail="x@exemplo.org", ou="CLIENTE-A", cpf="0",
                                      telefone="", senha=None)
    adm.banco.criar_convite({"nome": "Bruno Melo", "cpf": "99603082430", "email": "bm@exemplo.org",
                             "telefone": ""}, uid="brunomelo", organizacao="CLIENTE-A", convidado_por="chefe",
                            agora=adm.relogio())
    html = adm.client.get(_previa(adm, SEIS[:2])).text
    assert "O usuário anacosta já existe" in html and "reservado pelo convite" in html
    assert _caixas(html) == {0: (False, False), 1: (False, False)}  # corrigível editando o uid


def test_previa_marca_cpf_repetido_na_planilha(adm):
    html = adm.client.get(_previa(adm, [SEIS[0], ("Ana Costa Lima", "529.982.247-25", "outra@exemplo.org")])).text
    assert "repetido na planilha (linha 2)" in html
    assert _caixas(html)[1] == (False, True)


def _enviar_lote(amb, local, indices, **extra):
    data = {"organizacao": "CLIENTE-A", **{f"enviar_{i}": "sim" for i in indices}, **extra}
    return amb.client.post(local, data=data)


def test_criterio_20_seis_pessoas_geram_quatro_convites(adm):
    local = _previa(adm)
    html = adm.client.get(local).text
    marcadas = [i for i, (marcada, _) in _caixas(html).items() if marcada]
    assert marcadas == [0, 1, 2, 3]
    # o cliente envia também as linhas desmarcadas/desabilitadas: o servidor revalida e bloqueia
    r = _enviar_lote(adm, local, range(6))
    assert r.status_code == 200
    convites = _convidados(adm)
    assert sorted(c["email"] for c in convites) == ["ana@exemplo.org", "bruno@exemplo.org", "carla@exemplo.org",
                                                    "davi@exemplo.org"]
    assert {c["organizacao"] for c in convites} == {"CLIENTE-A"} and {c["origem"] for c in convites} == {"convite"}
    davi = next(c for c in convites if c["email"] == "davi@exemplo.org")
    assert (davi["cpf"], davi["telefone"], davi["uid_sugerido"]) == ("08301661305", "", "daviprado")
    assert len(adm.correio.enviados) == 4
    for c in convites:
        assert f'href="/admin/solicitacao/{c["id"]}"' in r.text
    assert r.text.count("bloqueado") == 2 and "CPF inválido" in r.text and "Confirme que é outra pessoa" in r.text
    [ultimo] = [a for a in auditoria(adm.banco) if a["acao"] == "lote_enviado"]
    assert ultimo["ator"] == "chefe" and ultimo["detalhe"] == "enviados=4 falhas=0 bloqueados=2"
    assert "@" not in ultimo["detalhe"] and _lotes(adm) == 0


def test_linha_ja_existente_enviada_como_outra_pessoa(adm):
    local = _previa(adm)
    _enviar_lote(adm, local, [4], outra_pessoa_4="sim")
    [c] = _convidados(adm)
    assert (c["email"], c["uid_sugerido"]) == ("elisa@exemplo.org", "elisateles")


def test_linha_invalida_forcada_e_bloqueada_no_servidor(adm):
    r = _enviar_lote(adm, _previa(adm), [5])
    assert r.status_code == 200 and "CPF inválido" in r.text and _convidados(adm) == []
    assert adm.correio.enviados == []


def test_uid_editado_por_linha(adm):
    local = _previa(adm)
    _enviar_lote(adm, local, [0, 1], uid_0="ABeatriz", uid_1="1x")
    [c] = _convidados(adm)
    assert c["uid_sugerido"] == "abeatriz"


def test_uids_repetidos_no_envio_sao_bloqueados(adm):
    local = _previa(adm)
    r = _enviar_lote(adm, local, [0, 1], uid_0="mesmo", uid_1="mesmo")
    assert [c["uid_sugerido"] for c in _convidados(adm)] == ["mesmo"] and "repetido" in r.text


def test_uid_que_passou_a_existir_no_ldap_e_bloqueado_no_envio(adm):
    local = _previa(adm)
    adm.dir.contas["anacosta"] = dict(uid="anacosta", cn="A", mail="z@exemplo.org", ou="CLIENTE-A", cpf="0",
                                      telefone="", senha=None)
    r = _enviar_lote(adm, local, [0])
    assert _convidados(adm) == [] and "O usuário anacosta já existe" in r.text


def test_cliente_do_lote_obrigatorio_e_cliente_novo_com_confirmacao(adm):
    local = _previa(adm)
    r = _enviar_lote(adm, local, [0], organizacao="")
    assert r.status_code == 400 and _convidados(adm) == [] and _lotes(adm) == 1
    r = _enviar_lote(adm, local, [0], organizacao="__nova__", organizacao_nova="NOVA")
    assert r.status_code == 400 and "Confirme a criação do cliente novo" in r.text and _convidados(adm) == []
    _enviar_lote(adm, local, [0], organizacao="__nova__", organizacao_nova="NOVA", confirmar_nova="sim")
    assert [c["organizacao"] for c in _convidados(adm)] == ["NOVA"]


def test_falha_de_smtp_aparece_no_resumo(adm):
    local = _previa(adm)
    adm.correio.falhar = True
    r = _enviar_lote(adm, local, [0, 1])
    assert r.status_code == 200 and r.text.count("falha de envio") == 2
    assert [c["link_enviado"] for c in _convidados(adm)] == [0, 0]
    assert auditoria(adm.banco)[0]["detalhe"] == "enviados=0 falhas=2 bloqueados=0"


def test_previa_expira_em_uma_hora(adm):
    local = _previa(adm)
    adm.relogio.avancar(minutes=59)
    assert adm.client.get(local).status_code == 200
    adm.relogio.avancar(minutes=2)
    r = adm.client.get(local)
    assert r.status_code == 410 and "expirou" in r.text
    assert _lotes(adm) == 0  # limpa as expiradas no acesso
    assert _enviar_lote(adm, local, [0]).status_code == 410 and _convidados(adm) == []


def test_lote_enviado_nao_pode_ser_reenviado(adm):
    local = _previa(adm)
    _enviar_lote(adm, local, [0])
    assert _enviar_lote(adm, local, [0]).status_code == 410 and len(_convidados(adm)) == 1


def test_lote_de_outro_admin_nao_e_acessivel(adm):
    local = _previa(adm)
    adm.client.post("/admin/sair")
    adm.dir.admins["outro"] = "Outro#123"
    _login(adm, "outro", "Outro#123")
    assert adm.client.get(local).status_code == 410


def test_previa_com_ldap_fora(adm):
    local = _previa(adm)
    adm.dir.falhar = True
    assert adm.client.get(local).status_code == 503


def test_convite_sem_telefone_pede_o_telefone_no_aceite(adm):
    _enviar_lote(adm, _previa(adm), [1])
    adm.client.post("/admin/sair")
    link = adm.correio.caminho_do_link()
    aceite = {"nome": "Bruno Dias Melo", "cpf": "111.444.777-35", "email": "bruno@exemplo.org", "telefone": "",
              "justificativa": "", "consentimento": "sim"}
    assert adm.client.post(link, data=aceite).status_code == 400
    r = adm.client.post(link, data={**aceite, "telefone": "(11) 97777-6666"})
    assert r.status_code == 302 and "/definir-senha/" in r.headers["Location"]
    assert adm.dir.contas["brunomelo"]["telefone"] == "+5511977776666"


def test_linha_com_campo_longo_fica_bloqueada(adm):
    html = adm.client.get(_previa(adm, [(SEIS[0][0], SEIS[0][1], "a" * 600 + "@exemplo.org"), SEIS[1]])).text
    assert "500 caracteres" in html and _caixas(html) == {0: (False, True), 1: (True, False)}


def test_lista_do_painel_apaga_previas_expiradas(adm):
    _previa(adm)
    adm.relogio.avancar(minutes=61)
    assert adm.client.get("/admin/").status_code == 200 and _lotes(adm) == 0


def test_email_repetido_na_planilha(adm):
    local = _previa(adm, [SEIS[0], ("Bruno Dias Melo", "111.444.777-35", "ANA@exemplo.org")])
    html = adm.client.get(local).text
    assert "E-mail repetido na planilha (linha 2)" in html and _caixas(html)[1] == (False, True)
    r = _enviar_lote(adm, local, [0, 1])
    assert [c["email"] for c in _convidados(adm)] == ["ana@exemplo.org"] and "E-mail repetido" in r.text
    # só a segunda marcada: não há repetição entre as marcadas
    local = _previa(adm, [SEIS[2], ("Davi Souza Prado", "08301661305", "carla@exemplo.org")])
    _enviar_lote(adm, local, [1])
    assert "carla@exemplo.org" in [c["email"] for c in _convidados(adm)]
