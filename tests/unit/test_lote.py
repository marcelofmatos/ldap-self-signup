from io import BytesIO

import openpyxl
import pytest

from app import lote


def xlsx(*linhas, folha_vazia_antes=False) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    if folha_vazia_antes:
        ws.title = "capa"
        ws = wb.create_sheet("dados")
    for linha in linhas:
        ws.append(list(linha))
    saida = BytesIO()
    wb.save(saida)
    return saida.getvalue()


def _campos(linhas):
    return [(l["nome"], l["cpf"], l["email"], l["telefone"]) for l in linhas]


def test_xlsx_com_cabecalho_reconhecido_por_nome_acento_e_caixa():
    conteudo = xlsx(("E-MAIL", "Nome Completo", "Celular", "C.P.F."),
                    ("ana@exemplo.org", "Ana Beatriz Costa", "(11) 91234-5678", "529.982.247-25"))
    linhas = lote.ler_planilha("pessoas.xlsx", conteudo)
    assert _campos(linhas) == [("Ana Beatriz Costa", "529.982.247-25", "ana@exemplo.org", "(11) 91234-5678")]
    assert linhas[0]["linha"] == 2


@pytest.mark.parametrize("cabecalho", [("nome", "cpf", "email", "telefone"), ("Name", "CPF", "Email", "Fone"),
                                       ("NOME", "Cpf", "e-mail", "Telefone")])
def test_variacoes_de_cabecalho(cabecalho):
    linhas = lote.ler_planilha("p.xlsx", xlsx(cabecalho, ("Ana Costa", "52998224725", "a@exemplo.org", "")))
    assert _campos(linhas) == [("Ana Costa", "52998224725", "a@exemplo.org", "")]


def test_xlsx_sem_cabecalho_usa_a_ordem_nome_cpf_email_telefone():
    linhas = lote.ler_planilha("p.xlsx", xlsx(("Ana Costa", "52998224725", "a@exemplo.org", "11912345678"),
                                              ("Bruno Dias", "11144477735", "b@exemplo.org")))
    assert _campos(linhas) == [("Ana Costa", "52998224725", "a@exemplo.org", "11912345678"),
                               ("Bruno Dias", "11144477735", "b@exemplo.org", "")]
    assert [l["linha"] for l in linhas] == [1, 2]


def test_cpf_numerico_e_normalizado_com_zeros_a_esquerda():
    linhas = lote.ler_planilha("p.xlsx", xlsx(("Ana Costa", 52998224725.0, "a@exemplo.org"),
                                              ("Bruno Dias", 1234567890, "b@exemplo.org"),
                                              ("Caio Lima", "11144477735.0", "c@exemplo.org"),
                                              ("Dora Melo", "1234567890", "d@exemplo.org")))
    assert [l["cpf"] for l in linhas] == ["52998224725", "01234567890", "11144477735", "01234567890"]


def test_telefone_numerico_vira_texto_sem_ponto_zero():
    [linha] = lote.ler_planilha("p.xlsx", xlsx(("Ana Costa", "52998224725", "a@exemplo.org", 11912345678.0)))
    assert linha["telefone"] == "11912345678"


def test_linhas_vazias_sao_ignoradas_e_espacos_removidos():
    conteudo = xlsx(("nome", "cpf", "email", "telefone"), (None, None, None, None), ("", " ", "\n", None),
                    ("Ana Beatriz  Costa \n", " 52998224725 ", " a@exemplo.org\n", " 11912345678 "))
    linhas = lote.ler_planilha("p.xlsx", conteudo)
    assert _campos(linhas) == [("Ana Beatriz Costa", "52998224725", "a@exemplo.org", "11912345678")]
    assert linhas[0]["linha"] == 4


def test_usa_a_primeira_folha_com_dados():
    [linha] = lote.ler_planilha("p.xlsx", xlsx(("Ana Costa", "52998224725", "a@exemplo.org"),
                                               folha_vazia_antes=True))
    assert linha["nome"] == "Ana Costa"


def test_csv_com_ponto_e_virgula_e_cabecalho():
    conteudo = "Nome;CPF;E-mail;Telefone\nAna Costa;52998224725.0;a@exemplo.org;11912345678\n\n".encode("utf-8-sig")
    assert _campos(lote.ler_planilha("p.CSV", conteudo)) == \
           [("Ana Costa", "52998224725", "a@exemplo.org", "11912345678")]


def test_csv_sem_cabecalho_em_latin1():
    conteudo = "José Conceição,11144477735,j@exemplo.org\n".encode("latin-1")
    assert _campos(lote.ler_planilha("p.csv", conteudo)) == [("José Conceição", "11144477735", "j@exemplo.org", "")]


def test_limite_de_linhas():
    assert len(lote.ler_planilha("p.xlsx", xlsx(*[("Ana Costa", "52998224725", "a@exemplo.org")] * 500))) == 500
    with pytest.raises(lote.PlanilhaInvalida, match="500"):
        lote.ler_planilha("p.xlsx", xlsx(*[("Ana Costa", "52998224725", "a@exemplo.org")] * 501))


def test_limite_de_tamanho():
    with pytest.raises(lote.PlanilhaInvalida, match="1 MB"):
        lote.ler_planilha("p.csv", b"a" * (lote.MAX_BYTES + 1))


@pytest.mark.parametrize("nome, conteudo", [("p.pdf", b"%PDF-1.4"), ("p", b"x"), ("p.xlsx", b"nao e zip"),
                                            ("p.xls", xlsx(("Ana Costa",)))])
def test_tipo_invalido_ou_arquivo_corrompido(nome, conteudo):
    with pytest.raises(lote.PlanilhaInvalida):
        lote.ler_planilha(nome, conteudo)


def test_planilha_sem_linhas():
    with pytest.raises(lote.PlanilhaInvalida, match="vazia"):
        lote.ler_planilha("p.xlsx", xlsx(("nome", "cpf", "email")))


def _zip(**entradas) -> bytes:
    import zipfile
    saida = BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dados in entradas.items():
            z.writestr(nome.replace("__", "/"), dados)
    return saida.getvalue()


def test_xlsx_largo_com_celulas_em_xfd_nao_estoura_a_memoria():
    import tracemalloc

    wb = openpyxl.Workbook()
    ws = wb.active
    for r in range(1, 2001):
        ws.cell(row=r, column=1, value="Ana Costa")
        ws.cell(row=r, column=16384, value="x")  # coluna XFD
    saida = BytesIO()
    wb.save(saida)
    conteudo = saida.getvalue()
    assert len(conteudo) < lote.MAX_BYTES
    tracemalloc.start()
    try:
        with pytest.raises(lote.PlanilhaInvalida, match="500"):
            lote.ler_planilha("p.xlsx", conteudo)
        _, pico = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert pico < 30 * 1024 * 1024


def test_xlsx_com_tamanho_descompactado_excessivo_e_recusado():
    conteudo = _zip(xl__worksheets__sheet1_xml=b"<" + b" " * (25 * 1024 * 1024))
    assert len(conteudo) < lote.MAX_BYTES
    with pytest.raises(lote.PlanilhaInvalida, match="descompactad"):
        lote.ler_planilha("p.xlsx", conteudo)


def test_xlsx_com_taxa_de_compressao_suspeita_e_recusado():
    conteudo = _zip(xl__worksheets__sheet1_xml=b" " * (5 * 1024 * 1024))
    with pytest.raises(lote.PlanilhaInvalida, match="descompactad"):
        lote.ler_planilha("p.xlsx", conteudo)


def test_xlsx_com_muitas_linhas_vazias_antes_dos_dados():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.cell(row=3000, column=1, value="Ana Costa")
    ws.cell(row=3000, column=2, value="52998224725")
    ws.cell(row=3000, column=3, value="a@exemplo.org")
    saida = BytesIO()
    wb.save(saida)
    [linha] = lote.ler_planilha("p.xlsx", saida.getvalue())
    assert (linha["linha"], linha["nome"]) == (3000, "Ana Costa")
    ws.cell(row=3000, column=1, value=None)
    ws.cell(row=60000, column=1, value="Ana Costa")
    saida = BytesIO()
    wb.save(saida)
    with pytest.raises(lote.PlanilhaInvalida, match="linhas"):
        lote.ler_planilha("p.xlsx", saida.getvalue())


def test_csv_com_campo_maior_que_o_limite_do_leitor():
    conteudo = b'Ana Costa,"' + b"x" * 200_000 + b'",a@exemplo.org\n'
    with pytest.raises(lote.PlanilhaInvalida, match="csv"):
        lote.ler_planilha("p.csv", conteudo)


def test_campo_longo_vira_erro_da_linha():
    [longa, ok] = lote.ler_planilha("p.csv", ("Ana " + "a" * 600 + ",52998224725,a@exemplo.org\n"
                                              "Bruno Dias,11144477735,b@exemplo.org\n").encode())
    assert len(longa["nome"]) == lote.MAX_CAMPO and "500 caracteres" in longa["erro"]
    assert "erro" not in ok


def test_csv_em_cp1252():
    conteudo = "José “Zé” Conceição – Silva,11144477735,j@exemplo.org\n".encode("cp1252")
    [linha] = lote.ler_planilha("p.csv", conteudo)
    assert linha["nome"] == "José “Zé” Conceição – Silva"
