"""Formatação para exibição no painel (filtros Jinja)."""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def data(valor: str | None, fuso: ZoneInfo) -> str:
    """ISO 8601 -> 'dd/mm/aaaa HH:MM' no fuso de exibição; vazio -> ''; texto não-ISO volta como veio."""
    if not valor:
        return ""
    try:
        momento = datetime.fromisoformat(valor)
    except ValueError:
        return valor
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.astimezone(fuso).strftime("%d/%m/%Y %H:%M")


def cpf(valor: str | None) -> str:
    d = re.sub(r"\D", "", valor or "")
    if len(d) != 11:
        return valor or ""
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def telefone(valor: str | None) -> str:
    """E.164 brasileiro -> '+55 (11) 91234-5678'; outros formatos voltam como vieram."""
    m = re.fullmatch(r"\+55(\d{2})(\d{4,5})(\d{4})", valor or "")
    if not m:
        return valor or ""
    return f"+55 ({m[1]}) {m[2]}-{m[3]}"


def cpf_mascarado(valor: str | None) -> str:
    """'52998224725' -> '***.982.247-**'; vazio -> ''; fora do padrão -> '***'."""
    d = re.sub(r"\D", "", valor or "")
    if not d:
        return ""
    return f"***.{d[3:6]}.{d[6:9]}-**" if len(d) == 11 else "***"
