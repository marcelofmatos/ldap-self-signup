import hashlib
from pathlib import Path

import pytest

from app.tema import Email, ErroTema, Tema

EXEMPLO = Path(__file__).resolve().parents[2] / "templates-exemplo" / "exemplo"


@pytest.fixture
def dir_template(tmp_path):
    d = tmp_path / "template"
    d.mkdir()
    (d / "privacidade.md").write_text("# Aviso\n\nUsamos seus dados <script>x</script>.\n", encoding="utf-8")
    return d


def test_sem_privacidade_nao_sobe(tmp_path):
    with pytest.raises(ErroTema, match="privacidade"):
        Tema(tmp_path)


def test_privacidade_versao_e_html_sem_html_bruto(dir_template):
    t = Tema(dir_template)
    texto = (dir_template / "privacidade.md").read_text(encoding="utf-8")
    assert t.privacidade_versao == hashlib.sha256(texto.encode()).hexdigest()
    assert "<h1>Aviso</h1>" in t.privacidade_html
    assert "<script>" not in t.privacidade_html


def test_tema_toml_padrao_e_sobreposicao(dir_template):
    assert Tema(dir_template).dados["nome"] == "Plataforma"
    (dir_template / "tema.toml").write_text('nome = "Exemplo"\n[links]\n"Chat" = "https://chat.x"\n')
    t = Tema(dir_template)
    assert t.dados["nome"] == "Exemplo"
    assert t.dados["cor_primaria"] == "#04559f"
    assert t.dados["links"] == {"Chat": "https://chat.x"}


def _tema_com_links(dir_template, links_toml):
    (dir_template / "tema.toml").write_text(f"[links]\n{links_toml}\n", encoding="utf-8")
    return Tema(dir_template)


def test_links_mistos_viram_servicos_com_icone(dir_template):
    t = _tema_com_links(dir_template, '"Arquivos" = "https://a"\n'
                        '"Wiki" = { url = "https://w", icone = "wiki", descricao = "Docs" }\n'
                        '"Grafana" = { url = "https://g" }\n"Outro" = "https://o"')
    assert t.dados["links"] == {"Arquivos": "https://a", "Wiki": "https://w", "Grafana": "https://g",
                                "Outro": "https://o"}
    assert list(t.dados["links"]) == ["Arquivos", "Wiki", "Grafana", "Outro"]
    assert t.dados["servicos"] == [
        {"rotulo": "Arquivos", "url": "https://a", "icone": "arquivos", "descricao": ""},
        {"rotulo": "Wiki", "url": "https://w", "icone": "wiki", "descricao": "Docs"},
        {"rotulo": "Grafana", "url": "https://g", "icone": "painel", "descricao": ""},
        {"rotulo": "Outro", "url": "https://o", "icone": "link", "descricao": ""},
    ]


def test_icone_do_rotulo_ignora_acento_e_caixa():
    from app.tema import icone_do_rotulo
    assert icone_do_rotulo("Reunião online") == "video"
    assert icone_do_rotulo("TROCA DE SENHA") == "senha"


@pytest.mark.parametrize("links_toml", [
    '"X" = { icone = "wiki" }',
    '"X" = 5',
    '"X" = { url = 5 }',
    '"X" = { url = "https://x", icone = "inexistente" }',
    '"X" = { url = "https://x", descricao = 3 }',
    '"X" = "javascript:alert(1)"',
    '"X" = { url = "data:text/html,x" }',
    '"X" = "//evil.example/x"',
    '"X" = { url = "//evil.example/x" }',
])
def test_links_invalidos_erro_tema(dir_template, links_toml):
    with pytest.raises(ErroTema):
        _tema_com_links(dir_template, links_toml)


def test_links_que_nao_e_tabela_erro_tema(dir_template):
    (dir_template / "tema.toml").write_text('links = ["https://x"]\n', encoding="utf-8")
    with pytest.raises(ErroTema):
        Tema(dir_template)


def test_url_relativa_ao_site_continua_valida(dir_template):
    assert _tema_com_links(dir_template, '"X" = "/ajuda"').dados["links"] == {"X": "/ajuda"}


def test_logo_opcional(dir_template):
    assert Tema(dir_template).logo is None
    (dir_template / "logo.png").write_bytes(b"\x89PNG")
    assert Tema(dir_template).logo == dir_template / "logo.png"


EMAILS_PADRAO = [
    ("confirmar_email", {"nome": "Maria", "link": "https://x/c/t", "validade": 24}, "Confirmar e-mail"),
    ("nova_solicitacao", {"nome": "Maria", "email": "m@x", "link": "https://x/a/1"}, "Revisar solicitação"),
    ("conta_aprovada", {"nome": "Maria", "uid": "mariasouza", "link": "https://x/d/t", "validade": 24,
                        "links": {"Chat": "https://chat.x"}}, "Definir minha senha"),
    ("reset_senha", {"nome": "Maria", "uid": "mariasouza", "link": "https://x/d/t", "validade": 24},
     "Redefinir senha"),
    ("confirmar_email_conta", {"nome": "Maria", "uid": "mariasouza", "link": "https://x/confirmar-email-conta/t",
                               "validade": 24}, "Confirmar e-mail"),
    ("confirmar_dados", {"nome": "Maria", "uid": "mariasouza", "link": "https://x/confirmar-dados/t", "validade": 24},
     "Conferir meus dados"),
    ("dados_atualizados", {"nome": "Maria", "uid": "mariasouza", "link": "https://x/d/t", "validade": 24},
     "Definir minha senha"),
    ("convite", {"nome": "Maria", "link": "https://x/convite/t", "validade_dias": 7, "convidado_por": "chefe"},
     "Aceitar convite"),
    ("convite_email", {"link": "https://x/convite/t", "validade_dias": 7, "convidado_por": "Maria"},
     "Fazer meu cadastro"),
    ("solicitacao_rejeitada", {"nome": "Maria", "motivo": "fora do escopo"}, None),
    ("alteracao_rejeitada", {"nome": "Maria", "motivo": "telefone errado"}, None),
]


@pytest.mark.parametrize("nome,ctx,botao", EMAILS_PADRAO)
def test_emails_padrao_renderizam(dir_template, nome, ctx, botao):
    email = Tema(dir_template).email(nome, **ctx)
    assert isinstance(email, Email)
    assert email.assunto.startswith("Plataforma")
    assert "Maria" in email.texto
    for cabecalho in ("Assunto:", "Botao:", "Você recebeu este e-mail porque"):
        assert cabecalho not in email.texto
    assert "Botao:" not in email.html
    assert email.html.startswith("<!doctype html>") and "<p>" in email.html
    assert "Você recebeu este e-mail porque" in email.html
    assert email.imagens == {}
    if botao:
        link = ctx["link"]
        assert f">{botao}</a>" in email.html
        assert email.html.count(f'href="{link}"') == 1  # só o botão; o endereço aparece em texto ao lado
        assert email.texto.count(link) == 1 and email.texto.rstrip().endswith(link)
    else:
        assert "Se o botão não funcionar" not in email.html


def test_email_assunto_e_botao_sao_escapados(dir_template):
    (dir_template / "emails").mkdir()
    (dir_template / "emails" / "reset_senha.md").write_text(
        "Assunto: <b>{{ nome }}</b>\nBotao: Ir <já>\n\nOi\n")
    email = Tema(dir_template).email("reset_senha", nome="Maria", link='https://x/"><script>')
    assert email.assunto == "<b>Maria</b>"
    assert "<title>&lt;b&gt;Maria&lt;/b&gt;</title>" in email.html
    assert "Ir &lt;já&gt;" in email.html
    assert "<script>" not in email.html and 'href="https://x/&#34;&gt;&lt;script&gt;"' in email.html


@pytest.mark.parametrize("link", ["javascript:alert(1)", "L", "ftp://x/y", ""])
def test_botao_so_com_link_http(dir_template, link):
    email = Tema(dir_template).email("reset_senha", nome="Maria", uid="m", link=link, validade=1)
    assert "Redefinir senha" not in email.html and "javascript:" not in email.html
    assert "Se o botão não funcionar" not in email.html
    assert "Redefinir senha" not in email.texto


def test_cabecalhos_em_qualquer_ordem_e_motivo_no_rodape(dir_template):
    (dir_template / "emails").mkdir()
    (dir_template / "emails" / "convite.md").write_text(
        "Assunto: Oi\nMotivo: Você recebeu porque sim.\nBotao: Entrar\n\nCorpo\n")
    email = Tema(dir_template).email("convite", link="https://x/c")
    assert ">Entrar</a>" in email.html and "Você recebeu porque sim." in email.html
    assert email.texto == "Corpo\n\nEntrar: https://x/c\n"


def test_sem_logo_mostra_nome_da_plataforma(dir_template):
    email = Tema(dir_template).email("solicitacao_rejeitada", nome="Maria", motivo="")
    assert "cid:logo" not in email.html and ">Plataforma<" in email.html


def test_logo_do_tema_vai_embutido(dir_template):
    (dir_template / "logo.png").write_bytes(b"\x89PNG-logo")
    email = Tema(dir_template).email("solicitacao_rejeitada", nome="Maria", motivo="")
    assert 'src="cid:logo"' in email.html and 'alt="Plataforma"' in email.html
    assert email.imagens == {"logo": (b"\x89PNG-logo", "png")}


def test_layout_do_tema_sobrescreve_o_padrao(dir_template):
    (dir_template / "emails").mkdir()
    (dir_template / "emails" / "_layout.html").write_text(
        "<i>{{ assunto }}|{{ corpo_html }}|{{ botao }}|{{ link }}|{{ tema.nome }}|{{ tem_logo }}</i>")
    email = Tema(dir_template).email("reset_senha", nome="Maria", uid="m", link="https://x/r", validade=1)
    assert email.html.startswith("<i>Plataforma — redefinição de senha|<p>Olá, Maria!</p>")
    assert email.html.endswith("|Redefinir senha|https://x/r|Plataforma|False</i>")


@pytest.mark.parametrize("nome,ctx,botao", EMAILS_PADRAO)
def test_layout_exemplo(nome, ctx, botao):
    """Tema de exemplo sem logo.png: o cabeçalho do e-mail mostra o nome do tema."""
    email = Tema(EXEMPLO).email(nome, **ctx)
    assert "Minha Plataforma" in email.assunto
    assert "cid:logo" not in email.html and email.imagens == {}
    assert ">Minha Plataforma</span>" in email.html
    assert "#f3f4f6" in email.html and "https://www.exemplo.org/" in email.html
    assert "Você recebeu este e-mail porque" in email.html
    if botao:
        assert f">{botao}</a>" in email.html and 'bgcolor="#334155"' in email.html


def test_favicon_padrao_e_do_tema(dir_template):
    t = Tema(dir_template)
    assert t.favicon_ico == t.padrao / "favicon.ico" and t.favicon_ico.is_file()
    assert t.favicon_png is None
    (dir_template / "favicon.ico").write_bytes(b"ico")
    (dir_template / "favicon.png").write_bytes(b"png")
    t = Tema(dir_template)
    assert t.favicon_ico == dir_template / "favicon.ico" and t.favicon_png == dir_template / "favicon.png"


def test_email_sobrescrito_pelo_template(dir_template):
    (dir_template / "emails").mkdir()
    (dir_template / "emails" / "reset_senha.md").write_text("Assunto: Troque já\n\nOi {{ nome }}: {{ link }}\n")
    email = Tema(dir_template).email("reset_senha", nome="Maria", uid="m", link="L", validade=1)
    assert email.assunto == "Troque já" and email.texto.strip() == "Oi Maria: L"


def test_email_sem_assunto_falha(dir_template):
    (dir_template / "emails").mkdir()
    (dir_template / "emails" / "reset_senha.md").write_text("Oi\n")
    with pytest.raises(ErroTema, match="Assunto"):
        Tema(dir_template).email("reset_senha", nome="M", uid="m", link="L", validade=1)


def test_link_do_email_sem_enfase(dir_template):
    link = "https://x.test/definir-senha/ab-_cd_-ef"
    email = Tema(dir_template).email("reset_senha", nome="Maria", uid="m", link=link, validade=1)
    assert f'href="{link}"' in email.html
    assert "<em>" not in email.html and "_cd_" in email.html
    assert link in email.texto


def test_links_extras_do_conta_aprovada_sao_autolinks(dir_template):
    email = Tema(dir_template).email("conta_aprovada", nome="Maria", uid="m", link="https://x/d/t",
                                     validade=1, links={"Chat": "https://chat.x/_a_"})
    assert '<a href="https://chat.x/_a_">' in email.html and "<em>" not in email.html


@pytest.mark.parametrize("tema", [None, EXEMPLO], ids=["padrao", "exemplo"])
def test_paginas_trazem_o_css_dos_componentes(tmp_path, tema):
    """Um base.html de tema que inclui _componentes.html recebe o CSS novo do app sem ser recopiado."""
    from app import create_app
    from tests.fakes import FakeCorreio, FakeDiretorio, Relogio, config_teste, template_teste

    cfg = config_teste(tmp_path, template_dir=tema or template_teste(tmp_path))
    app = create_app(cfg, diretorio=FakeDiretorio(), correio=FakeCorreio(), relogio=Relogio(), testing=True)
    html = app.test_client().get("/").text
    for regra in (".card-faltam{", "a.botao{", "button.icone{", "table.lista td.grupos{", ".st-alteracao{"):
        assert regra in html


def test_urls_seguras_aceitas(dir_template):
    t = _tema_com_links(dir_template, '"A" = "http://a"\n"B" = "mailto:x@y"\n"C" = "/interno"')
    assert list(t.dados["links"].values()) == ["http://a", "mailto:x@y", "/interno"]


def test_tema_exemplo_carrega_servicos():
    servicos = Tema(EXEMPLO).dados["servicos"]
    assert [(s["rotulo"], s["icone"]) for s in servicos] == [("Arquivos", "arquivos"), ("Wiki", "wiki"), ("Chat", "chat")]
    assert servicos[1]["descricao"] == "Documentação e manuais da equipe" and servicos[0]["descricao"] == ""


TOML_CLIENTES = (
    '[links]\n"Chat" = "https://chat.x"\n'
    '[links_por_cliente.CLIENTE-A]\n"Painel A" = { url = "https://a.x/", descricao = "Só do A" }\n'
    '[links_por_cliente."Cliente-B"]\n"Wiki B" = "https://b.x/"\n')


def _tema_clientes(dir_template, toml=TOML_CLIENTES):
    (dir_template / "tema.toml").write_text(toml, encoding="utf-8")
    return Tema(dir_template)


def test_links_por_cliente_somam_aos_gerais(dir_template):
    t = _tema_clientes(dir_template)
    assert set(t.por_cliente) == {"cliente-a", "cliente-b"}
    assert t.dados["links"] == {"Chat": "https://chat.x"} and len(t.dados["servicos"]) == 1
    a = t.servicos_do_cliente("CLIENTE-A")
    assert [s["rotulo"] for s in a] == ["Chat", "Painel A"] and a[1]["descricao"] == "Só do A"
    assert t.links_do_cliente("CLIENTE-A") == {"Chat": "https://chat.x", "Painel A": "https://a.x/"}


@pytest.mark.parametrize("ou", ["Cliente-A", "CLIENTE-A", "cliente-a", "  cliente-a "])
def test_cliente_normalizado_ignora_caixa_e_espacos(dir_template, ou):
    assert "Painel A" in t_links(dir_template, ou)


def t_links(dir_template, ou):
    return _tema_clientes(dir_template).links_do_cliente(ou)


def test_cliente_ignora_acento(dir_template):
    t = _tema_clientes(dir_template, '[links_por_cliente."Clíente-Á"]\n"X" = "https://x"\n')
    assert t.links_do_cliente("cliente-a") == {"X": "https://x"} and t.links_do_cliente("CLÍENTE-Á") == {"X": "https://x"}


@pytest.mark.parametrize("ou", ["", None, "CLIENTE-Z"])
def test_cliente_desconhecido_ou_vazio_so_gerais(dir_template, ou):
    t = _tema_clientes(dir_template)
    assert t.servicos_do_cliente(ou) == t.dados["servicos"] and t.links_do_cliente(ou) == {"Chat": "https://chat.x"}


@pytest.mark.parametrize("toml", [
    '[links_por_cliente.CLIENTE-A]\n"X" = "javascript:alert(1)"\n',
    '[links_por_cliente.CLIENTE-A]\n"X" = { url = "https://x", icone = "inexistente" }\n',
    '[links_por_cliente.CLIENTE-A]\n"X" = { descricao = "sem url" }\n',
    '[links_por_cliente]\nCLIENTE-A = "https://x"\n',
])
def test_links_por_cliente_invalidos_erro_tema(dir_template, toml):
    with pytest.raises(ErroTema):
        _tema_clientes(dir_template, toml)


def test_card_do_cliente_substitui_o_geral_de_mesmo_rotulo(dir_template):
    t = _tema_clientes(dir_template, '[links]\n"Chat" = "https://chat.x"\n"Wiki" = "https://w.x"\n'
                                     '[links_por_cliente.CLIENTE-A]\n"Chat" = "https://chat-a.x"\n"Painel" = "https://p.x"\n')
    assert [(s["rotulo"], s["url"]) for s in t.servicos_do_cliente("CLIENTE-A")] == [
        ("Chat", "https://chat-a.x"), ("Wiki", "https://w.x"), ("Painel", "https://p.x")]
    assert t.links_do_cliente("CLIENTE-A")["Chat"] == "https://chat-a.x"
