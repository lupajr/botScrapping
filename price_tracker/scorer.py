"""Cálculo de confiabilidade (média bayesiana), filtro de categorias/acessórios e ranqueamento."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ProductOffer
from .utils import clean_product_url, normalize, query_tokens

# Palavras típicas de acessórios baratos que poluem buscas de produtos principais
ACCESSORY_TERMS = (
    "pelicula",
    "capa",
    "capinha",
    "case",
    "bolsa",
    "estojo",
    "maleta",
    "protetor",
    "protecao",
    "adesivo",
    "skin",
    "suporte",
    "stand",
    "grip",
    "thumb",
    "borrachinha",
    "alca",
    "cabo",
    "carregador",
    "fonte",
    "adaptador",
    "dock",
    "porta jogos",
    "porta cartoes",
    "compativel com",
    "compativel p/",
    "volante",
)


@dataclass(frozen=True)
class CategoryRule:
    key: str
    label: str
    search_suffix: str = ""
    min_price: float | None = None
    block_accessories: bool = True
    extra_blocked_terms: tuple[str, ...] = ()
    required_any_terms: tuple[str, ...] = ()


CATEGORY_RULES: dict[str, CategoryRule] = {
    "geral": CategoryRule(
        key="geral",
        label="Geral (Sem Acessórios)",
        block_accessories=True,
    ),
    "videogames": CategoryRule(
        key="videogames",
        label="Video Games / Consoles",
        search_suffix="console",
        min_price=800.0,
        block_accessories=True,
        extra_blocked_terms=("jogo ", "midia fisica", "gift card", "cartao presente"),
    ),
    "controles": CategoryRule(
        key="controles",
        label="Controles / Gamepads",
        search_suffix="controle",
        min_price=70.0,
        block_accessories=True,
        required_any_terms=("controle", "joy-con", "joycon", "gamepad", "dualsense", "dualshock"),
    ),
    "jogos": CategoryRule(
        key="jogos",
        label="Jogos / Games",
        search_suffix="jogo",
        min_price=40.0,
        block_accessories=True,
        extra_blocked_terms=("console",),
    ),
    "celulares": CategoryRule(
        key="celulares",
        label="Celulares / Smartphones",
        search_suffix="smartphone",
        min_price=500.0,
        block_accessories=True,
        extra_blocked_terms=("lente", "aro", "fone"),
    ),
    "informatica": CategoryRule(
        key="informatica",
        label="Informática / Hardware",
        block_accessories=True,
    ),
    "acessorios": CategoryRule(
        key="acessorios",
        label="Acessórios",
        search_suffix="acessorios",
        block_accessories=False,
    ),
}

# Mapeamento de sinônimos digitados pelo usuário (ex: "/preco Nintendo Switch OLED video games")
CATEGORY_ALIASES: dict[str, str] = {
    "video games": "videogames",
    "video game": "videogames",
    "videogames": "videogames",
    "videogame": "videogames",
    "consoles": "videogames",
    "console": "videogames",
    "controles": "controles",
    "controle": "controles",
    "gamepad": "controles",
    "gamepads": "controles",
    "jogos": "jogos",
    "jogo": "jogos",
    "games": "jogos",
    "celulares": "celulares",
    "celular": "celulares",
    "smartphones": "celulares",
    "smartphone": "celulares",
    "informatica": "informatica",
    "hardware": "informatica",
    "acessorios": "acessorios",
    "acessorio": "acessorios",
    "geral": "geral",
}


def resolve_category(category: str | None) -> CategoryRule:
    if not category:
        return CATEGORY_RULES["geral"]
    norm = normalize(category).strip()
    key = CATEGORY_ALIASES.get(norm, norm)
    return CATEGORY_RULES.get(key, CATEGORY_RULES["geral"])


def extract_category_from_text(raw_text: str) -> tuple[str, str | None]:
    """Extrai a categoria caso o usuário digite no final do comando.

    Exemplos aceitos:
      - 'nintendo Switch OLED | video games' -> ('nintendo Switch OLED', 'videogames')
      - 'nintendo Switch OLED video games'   -> ('nintendo Switch OLED', 'videogames')
      - 'nintendo Switch OLED acessorios'    -> ('nintendo Switch OLED', 'acessorios')
    """
    text = raw_text.strip()
    if "|" in text:
        left, right = text.rsplit("|", 1)
        norm_right = normalize(right).strip()
        if norm_right in CATEGORY_ALIASES:
            return left.strip(), CATEGORY_ALIASES[norm_right]

    norm_text = normalize(text)
    # Ordena pelos aliases mais longos primeiro (ex: "video games" antes de "games")
    for alias in sorted(CATEGORY_ALIASES, key=len, reverse=True):
        pattern = rf"^(?P<prod>.+?)\s+{re.escape(alias)}$"
        match = re.match(pattern, norm_text)
        if match:
            prod_len = len(match.group("prod"))
            clean_prod = text[:prod_len].strip()
            if clean_prod:
                return clean_prod, CATEGORY_ALIASES[alias]

    return text, None


def build_store_search_query(query: str, category: str | None = None) -> str:
    """Enriquece a busca enviada às lojas com o termo da categoria quando necessário."""
    rule = resolve_category(category)
    if not rule.search_suffix:
        return query
    norm_q = normalize(query)
    if rule.search_suffix not in norm_q:
        return f"{rule.search_suffix} {query}".strip()
    return query


def compute_bayesian_rating(
    rating: float,
    reviews: int,
    min_reviews_threshold: int = 500,
    baseline_rating: float = 3.5,
) -> float:
    """Média bayesiana calibrada para camada anti-golpe (limiar de 500 avaliações)."""
    if reviews <= 0 or rating <= 0:
        return round(baseline_rating * 0.7, 2)
    v, m = reviews, min_reviews_threshold
    weighted = (v / (v + m)) * rating + (m / (v + m)) * baseline_rating
    return round(weighted, 2)


def is_accessory_title(norm_title: str, norm_query: str) -> bool:
    """Retorna True se o título for de um acessório (capa, película, case, etc.) não pedido na busca."""
    for term in ACCESSORY_TERMS:
        if term in norm_query:
            continue
        if re.search(rf"\b{re.escape(term)}\b", norm_title):
            return True
    # Padrão clássico de acessório: "... para Nintendo Switch" / "... p/ iPhone"
    first_token = query_tokens(norm_query)[0] if query_tokens(norm_query) else ""
    if first_token and re.search(rf"\b(?:para|p/)\s+{re.escape(first_token)}\b", norm_title):
        if not norm_title.startswith(first_token) and "console" not in norm_title[:25]:
            return True
    return False


def is_relevant(offer: ProductOffer, query: str, category: str | None = None) -> bool:
    """Verifica se o anúncio contém os termos buscados e respeita a categoria escolhida."""
    norm_title = normalize(offer.title)
    norm_query = normalize(query)
    title_tokens = set(re.findall(r"[a-z0-9]+", norm_title))

    if not all(token in title_tokens for token in query_tokens(query)):
        return False

    rule = resolve_category(category)

    if rule.block_accessories and is_accessory_title(norm_title, norm_query):
        return False

    for blocked in rule.extra_blocked_terms:
        if blocked not in norm_query and blocked in norm_title:
            return False

    if rule.required_any_terms:
        if not any(req in norm_title for req in rule.required_any_terms):
            return False

    return True


def rank_top_cheapest_and_reliable(
    offers: list[ProductOffer],
    query: str,
    top_k: int = 3,
    min_required_reviews: int = 500,
    min_acceptable_rating: float = 4.0,
    min_price: float | None = None,
    max_price: float | None = None,
    category: str | None = None,
) -> tuple[list[ProductOffer], bool]:
    """Filtra ofertas relevantes que atingem o piso anti-golpe (500+ avaliações por padrão)
    e ordena estritamente pelo menor preço.
    """
    rule = resolve_category(category)
    effective_min_price = min_price if min_price is not None else rule.min_price

    for offer in offers:
        offer.url = clean_product_url(offer.url)
        offer.reliability_score = compute_bayesian_rating(
            offer.rating, offer.reviews_count, min_reviews_threshold=max(min_required_reviews, 20)
        )

    candidates = [o for o in offers if is_relevant(o, query, category=category)]
    if effective_min_price is not None:
        candidates = [o for o in candidates if o.price >= effective_min_price]
    if max_price is not None:
        candidates = [o for o in candidates if o.price <= max_price]

    # Remove anúncios duplicados (mesmo link) mantendo o primeiro.
    unique: dict[str, ProductOffer] = {}
    for offer in candidates:
        unique.setdefault(offer.url.split("?")[0], offer)
    candidates = list(unique.values())

    reliable = [
        o
        for o in candidates
        if o.reviews_count >= min_required_reviews and o.reliability_score >= min_acceptable_rating
    ]

    if reliable:
        # Camada estrita anti-golpe: se há ofertas com 500+ avaliações, retorna SOMENTE elas
        # (nunca mistura anúncios sem avaliações junto com os confiáveis).
        reliable.sort(key=lambda o: (o.price, -o.reliability_score, -o.reviews_count))
        return reliable[:top_k], False

    # Fallback seguro caso nenhum anúncio nas 4 lojas tenha atingido 500 avaliações:
    # prioriza os que têm mais avaliações (nunca anúncios com 0 avaliações)
    rated_candidates = [o for o in candidates if o.reviews_count >= 50 and o.rating >= 4.0]
    rated_candidates.sort(key=lambda o: (-o.reviews_count, o.price))
    return rated_candidates[:top_k], True
