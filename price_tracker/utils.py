"""Funções auxiliares para limpar texto vindo do HTML das lojas."""

from __future__ import annotations

import re
import unicodedata


def parse_brl_price(text: str | None) -> float | None:
    """Converte 'R$ 1.234,56' / '1.234' / '1234,5' em float. Retorna None se inválido."""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,.]", "", text)
    if not cleaned:
        return None
    # Formato brasileiro: ponto = milhar, vírgula = decimal.
    if "," in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(".", "")
    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def parse_rating(text: str | None) -> float:
    """Extrai a nota de textos como '4,6 de 5 estrelas' ou '4.6'."""
    if not text:
        return 0.0
    match = re.search(r"(\d+(?:[.,]\d+)?)", text)
    if not match:
        return 0.0
    value = float(match.group(1).replace(",", "."))
    return value if 0 <= value <= 5 else 0.0


def parse_count(text: str | None) -> int:
    """Extrai quantidades como '(1.234)', '1,2 mil', '2 mil avaliações', '+10mil vendidos'."""
    if not text:
        return 0
    lowered = text.lower()
    match = re.search(r"(\d+(?:[.,]\d+)*)\s*(mil|k)?", lowered)
    if not match:
        return 0
    number, multiplier = match.group(1), match.group(2)
    if multiplier:
        # '1,2 mil' -> 1200 ; '1.2k' -> 1200
        value = float(number.replace(".", "").replace(",", ".") if "," in number else number)
        return int(value * 1000)
    return int(re.sub(r"[.,]", "", number))


def normalize(text: str) -> str:
    """Minúsculas e sem acentos, para comparar títulos com a busca."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def query_tokens(query: str) -> list[str]:
    """Palavras relevantes da busca (ignora palavras curtas como 'de', 'e')."""
    stopwords = {"de", "da", "do", "das", "dos", "e", "com", "para", "pra", "o", "a", "em"}
    tokens = re.findall(r"[a-z0-9]+", normalize(query))
    return [t for t in tokens if t not in stopwords]


def clean_product_url(url: str) -> str:
    """Remove parâmetros de rastreamento gigantes para deixar o link curto e clicável no terminal."""
    if not url:
        return url
    # Amazon: unifica qualquer link do mesmo ASIN para https://www.amazon.com.br/dp/<ASIN>
    amz_asin = re.search(r"amazon\.com\.br(?:/[^/?#]+)?/dp/([A-Z0-9]{10})", url)
    if amz_asin:
        return f"https://www.amazon.com.br/dp/{amz_asin.group(1)}"
    # Remove query strings e fragmentos de tracking (#position=..., ?dib=...)
    return url.split("?")[0].split("#")[0]

