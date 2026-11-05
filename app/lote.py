"""Convites em lote: leitura da planilha (.xlsx/.csv) e prévia por linha (spec §17.1)."""
import csv
import io
import re
import zipfile

from . import contas

MAX_BYTES = 1024 * 1024
MAX_LINHAS = 500
MAX_CAMPO = 500  # caracteres por célula; acima disso a linha fica com erro
MAX_COLUNAS = 10  # colunas lidas por linha; o resto é ignorado
MAX_VARRIDAS = 10 * MAX_LINHAS  # linhas percorridas (inclusive vazias) antes de desistir
MAX_DESCOMPACTADO = 20 * 1024 * 1024  # soma das partes do .xlsx descompactadas
MAX_TAXA = 100  # compressão máxima de uma parte grande do .xlsx
COLUNAS = ("nome", "cpf", "email", "telefone")
_CABECALHOS = {
    "nome": "nome", "name": "nome", "nomecompleto": "nome",
    "cpf": "cpf",
    "email": "email", "mail": "email",
    "telefone": "telefone", "fone": "telefone", "celular": "telefone", "phone": "telefone", "tel": "telefone",
}
_NUMERO_RE = re.compile(r"\d+(\.0+)?")


class PlanilhaInvalida(ValueError):
    pass


def ler_planilha(nome_arquivo: str, conteudo: bytes) -> list[dict]:
    """Linhas não vazias da planilha: dicts com `linha` (número na planilha) e as colunas de COLUNAS."""
    if len(conteudo) > MAX_BYTES:
        raise PlanilhaInvalida("Arquivo maior que 1 MB.")
    extensao = nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else ""
    if extensao == "xlsx":
        celulas = _celulas_xlsx(conteudo)
    elif extensao == "csv":
        celulas = _celulas_csv(conteudo)
    else:
        raise PlanilhaInvalida("Envie uma planilha .xlsx ou .csv.")
    linhas = []
    for varridas, (n, valores) in enumerate(celulas, 1):  # leitura preguiçosa: para assim que passa do limite
        if varridas > MAX_VARRIDAS:
            raise PlanilhaInvalida(f"A planilha tem linhas demais (inclusive vazias): o limite é {MAX_VARRIDAS}.")
        if any(valores):
            linhas.append((n, valores))
            if len(linhas) > MAX_LINHAS + 1:  # + cabeçalho
                break
    posicoes = dict(zip(COLUNAS, range(len(COLUNAS))))
    if linhas:
        cabecalho = {}
        for i, valor in enumerate(linhas[0][1]):
            coluna = _CABECALHOS.get(re.sub(r"[^a-z]", "", contas.sem_acento(valor).lower()))
            if coluna:
                cabecalho.setdefault(coluna, i)
        if cabecalho:
            faltando = [c for c in ("nome", "cpf", "email") if c not in cabecalho]
            if faltando:
                raise PlanilhaInvalida(f"O cabeçalho não tem a coluna {', '.join(faltando)}.")
            posicoes, linhas = cabecalho, linhas[1:]
    if not linhas:
        raise PlanilhaInvalida("A planilha está vazia.")
    if len(linhas) > MAX_LINHAS:
        raise PlanilhaInvalida(f"A planilha tem mais de {MAX_LINHAS} linhas.")
    resultado = []
    for n, valores in linhas:
        linha = {"linha": n}
        for coluna in COLUNAS:
            i = posicoes.get(coluna)
            linha[coluna] = valores[i] if i is not None and i < len(valores) else ""
            if len(linha[coluna]) > MAX_CAMPO:
                linha[coluna] = linha[coluna][:MAX_CAMPO]
                linha["erro"] = f"Célula com mais de {MAX_CAMPO} caracteres."
        if _NUMERO_RE.fullmatch(linha["cpf"]):  # CPF que virou número perde os zeros à esquerda
            linha["cpf"] = linha["cpf"].split(".")[0].zfill(11)
        resultado.append(linha)
    return resultado


def _texto(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    return " ".join(str(valor).split())


def _conferir_zip(conteudo: bytes) -> None:
    """Recusa .xlsx que não é zip ou que descompacta demais (zip bomb) antes de entregar ao openpyxl."""
    try:
        with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
            partes = z.infolist()
    except zipfile.BadZipFile as e:
        raise PlanilhaInvalida("Não foi possível ler a planilha .xlsx.") from e
    if sum(p.file_size for p in partes) > MAX_DESCOMPACTADO or any(
            p.file_size > MAX_BYTES and p.file_size > MAX_TAXA * max(p.compress_size, 1) for p in partes):
        raise PlanilhaInvalida("A planilha .xlsx descompactada é grande demais.")


def _celulas_xlsx(conteudo: bytes):
    """(número, textos das MAX_COLUNAS primeiras células) de cada linha da primeira folha com dados."""
    import openpyxl  # só quem envia .xlsx paga o import

    _conferir_zip(conteudo)
    try:  # arquivo enviado pelo usuário: qualquer falha do leitor é planilha inválida
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
        try:
            for folha in wb.worksheets:
                tem_dados = False
                for n, valores in enumerate(folha.iter_rows(max_col=MAX_COLUNAS, values_only=True), 1):
                    textos = [_texto(v) for v in valores]
                    tem_dados = tem_dados or any(textos)
                    yield n, textos
                if tem_dados:
                    return
        finally:
            wb.close()
    except Exception as e:
        raise PlanilhaInvalida("Não foi possível ler a planilha .xlsx.") from e


def _celulas_csv(conteudo: bytes):
    for codificacao in ("utf-8-sig", "cp1252"):  # cp1252: CSV salvo pelo Excel em português
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = conteudo.decode("latin-1")
    primeira = next((l for l in texto.splitlines() if l.strip()), "")
    delimitador = max(";,\t", key=primeira.count)
    try:
        for n, valores in enumerate(csv.reader(io.StringIO(texto), delimiter=delimitador), 1):
            yield n, [_texto(v) for v in valores[:MAX_COLUNAS]]
    except csv.Error as e:
        raise PlanilhaInvalida("Não foi possível ler a planilha .csv.") from e


def previa(s, linhas: list[dict], uids: dict[int, str] | None = None, so: set[int] | None = None) -> list[dict]:
    """Valida cada linha e procura conflitos no LDAP. `uids`: uid escolhido por índice (senão, o sugerido);
    `so`: só estes índices (repetições de CPF/e-mail/uid contam só entre eles).

    Cada item: i, linha, dados (normalizados quando válidos), uid, erros (dados da pessoa; impedem o envio),
    erro_uid (corrigível editando o uid), conflitos (CPF/e-mail já existentes) e marcada (o padrão da prévia).
    Levanta ErroDiretorio se o LDAP estiver fora.
    """
    uids = uids or {}
    itens, vistos, uids_vistos = [], {"cpf": {}, "email": {}}, {}
    for i, linha in enumerate(linhas):
        if so is not None and i not in so:
            continue
        dados, erros = contas.validar_formulario({**linha, "justificativa": ""}, justificativa_opcional=True)
        if not linha["telefone"]:  # no lote o telefone é opcional: a pessoa informa no aceite
            erros.pop("telefone", None)
            dados["telefone"] = ""
        if "erro" in linha:
            erros["linha"] = linha["erro"]
        for campo, rotulo in (("cpf", "CPF"), ("email", "E-mail")):
            if campo in dados:
                if dados[campo] in vistos[campo]:
                    erros[campo] = f"{rotulo} repetido na planilha (linha {vistos[campo][dados[campo]]})."
                vistos[campo].setdefault(dados[campo], linha["linha"])
        item = {"i": i, "linha": linha["linha"], "dados": {**linha, **dados}, "erros": erros, "erro_uid": None,
                "conflitos": {"uid": [], "cpf": [], "mail": []}}
        uid = uids.get(i, "").strip().lower()
        if not uid and "nome" in dados:
            uid = contas.derivar_nomes(dados["nome"])["uid"]
        item["uid"] = uid
        if not erros:
            try:
                contas.validar_uid(uid)
            except contas.DadosInvalidos as e:
                item["erro_uid"] = str(e)
            item["conflitos"] = s.diretorio.conflitos(uid, dados["cpf"], dados["email"])
            if not item["erro_uid"]:
                reservado = s.banco.convite_aberto_com_uid(uid, exceto_cpf=dados["cpf"])
                if item["conflitos"]["uid"]:
                    item["erro_uid"] = f"O usuário {uid} já existe. Escolha outro."
                elif reservado is not None:
                    item["erro_uid"] = f"O usuário {uid} já está reservado pelo convite #{reservado}."
                elif uid in uids_vistos:
                    item["erro_uid"] = f"O usuário {uid} está repetido no lote (linha {uids_vistos[uid]})."
                uids_vistos.setdefault(uid, linha["linha"])
        item["existe"] = bool(item["conflitos"]["cpf"] or item["conflitos"]["mail"])
        item["marcada"] = not (erros or item["erro_uid"] or item["existe"])
        itens.append(item)
    return itens
