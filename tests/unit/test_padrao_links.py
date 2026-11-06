"""Links de navegação ficam em pílulas (<p class="badges"><a class="badge">), não soltos como texto."""
import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[2] / "app" / "templates"
SOLTO = re.compile(r'<p( class="mudo")?>[^<]*<a href=')
EXCECOES = {"publico.privacidade"}  # o aviso de privacidade faz parte da frase do consentimento


def test_nenhum_link_de_navegacao_solto():
    soltos = []
    for arq in TEMPLATES.rglob("*.html"):
        for n, linha in enumerate(arq.read_text(encoding="utf-8").splitlines(), 1):
            if SOLTO.search(linha) and not any(e in linha for e in EXCECOES):
                soltos.append(f"{arq.relative_to(TEMPLATES)}:{n}: {linha.strip()}")
    assert soltos == []
