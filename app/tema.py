"""Tema do deploy (/template) com fallback para o padrão embutido (app/tema_padrao)."""
import hashlib
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, StrictUndefined
from markdown_it import MarkdownIt
from markupsafe import Markup

PADRAO = Path(__file__).parent / "tema_padrao"
PAGINAS_PADRAO = Path(__file__).parent / "templates"
_md = MarkdownIt("commonmark", {"html": False})
_LINK_SEGURO = re.compile(r"https?://\S+\Z", re.IGNORECASE)
_CABECALHOS = {"Botao:": "botao", "Motivo:": "motivo"}
ICONES = ("arquivos", "senha", "chat", "email", "wiki", "painel", "video", "agenda", "link")
URLS_SEGURAS = ("http://", "https://", "mailto:")
PALAVRAS_ICONE = (("arquivos", ("arquivo", "drive", "nuvem", "files")), ("senha", ("senha", "password")),
                  ("chat", ("chat", "mensage", "conversa")), ("email", ("e-mail", "email", "correio", "webmail")),
                  ("wiki", ("wiki", "doc", "manual", "ajuda")),
                  ("painel", ("painel", "dashboard", "grafana", "relat", "monitor")),
                  ("video", ("reuni", "video", "meet", "jitsi")), ("agenda", ("agenda", "calend")))


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()


def icone_do_rotulo(rotulo: str) -> str:
    r = _sem_acento(rotulo)
    for icone, palavras in PALAVRAS_ICONE:
        if any(_sem_acento(p) in r for p in palavras):
            return icone
    return "link"


@dataclass(frozen=True)
class Email:
    assunto: str
    texto: str
    html: str
    imagens: dict  # Content-ID -> (bytes, subtipo de image/*), embutidas no HTML como cid:<id>


class ErroTema(ValueError):
    pass


def md_para_html(texto: str) -> str:
    """Markdown → HTML sem HTML bruto (tags no texto viram texto escapado)."""
    return _md.render(texto)


class Tema:
    def __init__(self, dir_template: Path, dir_padrao: Path = PADRAO):
        self.dir = Path(dir_template)
        self.padrao = Path(dir_padrao)
        privacidade = self.dir / "privacidade.md"
        if not privacidade.is_file():
            raise ErroTema(f"aviso de privacidade obrigatório ausente: {privacidade}")
        self.privacidade_texto = privacidade.read_text(encoding="utf-8")
        self.privacidade_versao = hashlib.sha256(self.privacidade_texto.encode("utf-8")).hexdigest()
        self.privacidade_html = md_para_html(self.privacidade_texto)
        self.dados = self._carregar_toml()
        carregador = ChoiceLoader([FileSystemLoader(str(self.dir / "emails")),
                                   FileSystemLoader(str(self.padrao / "emails"))])
        self._env_email = Environment(loader=carregador, undefined=StrictUndefined, autoescape=False,
                                      keep_trailing_newline=True)
        self._env_layout = Environment(loader=carregador, undefined=StrictUndefined, autoescape=True)

    def _carregar_toml(self) -> dict:
        dados = tomllib.loads((self.padrao / "tema.toml").read_text(encoding="utf-8"))
        arquivo = self.dir / "tema.toml"
        if arquivo.is_file():
            for chave, valor in tomllib.loads(arquivo.read_text(encoding="utf-8")).items():
                if isinstance(valor, dict) and isinstance(dados.get(chave), dict):
                    dados[chave] = {**dados[chave], **valor}
                else:
                    dados[chave] = valor
        dados["links"], dados["servicos"] = self._normalizar_links(dados.get("links", {}))
        return dados

    @staticmethod
    def _normalizar_links(links: dict) -> tuple[dict, list]:
        """[links] aceita rótulo = "url" ou rótulo = { url, icone?, descricao? }."""
        if not isinstance(links, dict):
            raise ErroTema("[links] deve ser uma tabela (rótulo = \"url\")")
        urls, servicos = {}, []
        for rotulo, valor in links.items():
            if isinstance(valor, str):
                valor = {"url": valor}
            if not isinstance(valor, dict) or not isinstance(valor.get("url"), str):
                raise ErroTema(f"link '{rotulo}': use uma URL ou uma tabela com 'url'")
            url = valor["url"]
            if not (url.lower().startswith(URLS_SEGURAS) or (url.startswith("/") and not url.startswith("//"))):
                raise ErroTema(f"link '{rotulo}': a URL deve começar com http://, https://, mailto: ou /")
            icone = valor.get("icone") or icone_do_rotulo(rotulo)
            if icone not in ICONES:
                raise ErroTema(f"link '{rotulo}': ícone '{icone}' desconhecido (válidos: {', '.join(ICONES)})")
            descricao = valor.get("descricao", "")
            if not isinstance(descricao, str):
                raise ErroTema(f"link '{rotulo}': 'descricao' deve ser texto")
            urls[rotulo] = valor["url"]
            servicos.append({"rotulo": rotulo, "url": valor["url"], "icone": icone, "descricao": descricao})
        return urls, servicos

    def _arquivo(self, nome: str) -> Path | None:
        """Arquivo do tema, senão o do padrão embutido, senão None."""
        for base in (self.dir, self.padrao):
            caminho = base / nome
            if caminho.is_file():
                return caminho
        return None

    @property
    def logo(self) -> Path | None:
        return self._arquivo("logo.png")

    @property
    def favicon_ico(self) -> Path:
        return self._arquivo("favicon.ico")  # o padrão embutido sempre existe

    @property
    def favicon_png(self) -> Path | None:
        return self._arquivo("favicon.png")

    def carregador_paginas(self) -> ChoiceLoader:
        return ChoiceLoader([FileSystemLoader(str(self.dir / "paginas")), FileSystemLoader(str(PAGINAS_PADRAO))])

    def email(self, modelo: str, /, **ctx) -> Email:
        """Renderiza emails/<nome>.md no emails/_layout.html.

        Cabeçalho do .md: 'Assunto: ...' na 1ª linha e, opcionais, 'Botao: <rótulo>' e 'Motivo: <texto>'.
        O botão só aparece com rótulo e um ``link`` http(s); nesse caso o link vai ao fim da parte texto.
        """
        bruto = self._env_email.get_template(f"{modelo}.md").render(plataforma=self.dados["nome"], **ctx)
        primeira, _, corpo = bruto.partition("\n")
        if not primeira.startswith("Assunto:"):
            raise ErroTema(f"e-mail {modelo}.md deve começar com 'Assunto:'")
        assunto = primeira[len("Assunto:"):].strip()
        cab = {"botao": None, "motivo": None}
        while (prefixo := next((p for p in _CABECALHOS if corpo.startswith(p)), None)):
            linha, _, corpo = corpo.partition("\n")
            cab[_CABECALHOS[prefixo]] = linha[len(prefixo):].strip()
        corpo = corpo.lstrip("\n")
        link = ctx.get("link")
        link = link if isinstance(link, str) and _LINK_SEGURO.match(link) else None
        botao = cab["botao"] if link else None
        texto = f"{corpo.rstrip()}\n\n{botao}: {link}\n" if botao else corpo
        logo = self.logo
        html = self._env_layout.get_template("_layout.html").render(
            corpo_html=Markup(md_para_html(corpo)), assunto=assunto, botao=botao, link=link if botao else None,
            tema=self.dados, tem_logo=logo is not None,
            motivo_envio=cab["motivo"] or f"Você recebeu este e-mail porque este endereço foi informado na "
                                          f"{self.dados['nome']}.",
        )
        imagens = {"logo": (logo.read_bytes(), "png")} if logo else {}
        return Email(assunto, texto, html, imagens)
