"""Cálculo de confiabilidade (média bayesiana), filtro de categorias/acessórios e ranqueamento."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ProductOffer
from .utils import clean_product_url, normalize, query_tokens

# Palavras puramente de acessórios (raramente representam o produto principal)
PURE_ACCESSORY_TERMS = {
    "pelicula",
    "capinha",
    "skin",
    "adesivo",
    "estojo",
    "bag",
    "maleta",
    "thumb grip",
    "borrachinha",
    "porta jogos",
    "porta cartoes",
    "earpad",
    "earpads",
    "almofada",
    "almofadas",
    "skates",
    "feets",
    "grip tape",
}

# Palavras contextuais de acessórios (podem ser acessórios OU características do produto, ex: 'com cabo USB-C')
CONTEXT_ACCESSORY_TERMS = {
    "cabo",
    "carregador",
    "fonte",
    "adaptador",
    "suporte",
    "dock",
    "case",
    "capa",
    "alca",
    "dongle",
}

# Sinônimos de tipos de produto para evitar descartar anúncios legítimos
DEVICE_SYNONYMS = {
    "fone": {"fone", "fones", "headset", "headsets", "headphone", "headphones", "auricular", "earphone", "earphones", "earbuds", "earbud"},
    "headset": {"fone", "fones", "headset", "headsets", "headphone", "headphones", "auricular", "earphone", "earbuds"},
    "headphone": {"fone", "fones", "headset", "headsets", "headphone", "headphones", "auricular"},
    "celular": {"celular", "celulares", "smartphone", "smartphones", "telefone", "telefones"},
    "smartphone": {"celular", "celulares", "smartphone", "smartphones", "telefone"},
    "videogame": {"videogame", "videogames", "console", "consoles"},
    "videogames": {"videogame", "videogames", "console", "consoles"},
    "computador": {"computador", "pc", "desktop"},
}


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
    # 1. Se a busca do usuário pediu o termo explicitamente, não bloqueia
    for term in PURE_ACCESSORY_TERMS | CONTEXT_ACCESSORY_TERMS:
        if term in norm_query:
            return False

    # 2. Termos estritamente de acessórios: se aparecerem no título, é acessório
    for term in PURE_ACCESSORY_TERMS:
        if re.search(rf"\b{re.escape(term)}\b", norm_title):
            return True

    # 3. Termos contextuais: são acessórios SE o título começar com eles (ex: 'Cabo USB para...', 'Adaptador...', 'Case...')
    first_title_word = norm_title.split()[0] if norm_title.split() else ""
    if first_title_word in CONTEXT_ACCESSORY_TERMS:
        return True

    # 4. Padrões relacionais: 'cabo/adaptador/case/capa para/p/compativel'
    for term in CONTEXT_ACCESSORY_TERMS:
        pattern = rf"\b{re.escape(term)}\b(?:\s+\w+){{0,3}}\s+(?:para|p/|compativel com|indicado para)\b"
        if re.search(pattern, norm_title):
            return True

    # 5. Padrão clássico de acessório: "... para Nintendo Switch" / "... p/ iPhone"
    first_token = query_tokens(norm_query)[0] if query_tokens(norm_query) else ""
    if first_token and re.search(rf"\b(?:para|p/)\s+{re.escape(first_token)}\b", norm_title):
        main_device_prefixes = ("console", "headset", "fone", "mouse", "smartphone", "celular", "teclado")
        if not norm_title.startswith(first_token) and not any(norm_title.startswith(w) for w in main_device_prefixes):
            return True

    return False


def token_matches(token: str, title_tokens: set[str]) -> bool:
    """Verifica se o token ou seus sinônimos equivalentes aparecem nos tokens do título."""
    if token in title_tokens:
        return True
    if token in DEVICE_SYNONYMS:
        return any(syn in title_tokens for syn in DEVICE_SYNONYMS[token])
    return False


def is_relevant(offer: ProductOffer, query: str, category: str | None = None) -> bool:
    """Verifica se o anúncio contém os termos buscados e respeita a categoria escolhida."""
    norm_title = normalize(offer.title)
    norm_query = normalize(query)
    title_tokens = set(re.findall(r"[a-z0-9]+", norm_title))

    if not all(token_matches(token, title_tokens) for token in query_tokens(query)):
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
    """Filtra ofertas relevantes em camadas progressivas de segurança:
    1. Tier 1 (Anti-Golpe): se houver ofertas com 500+ avaliações (ou o piso configurado), usa somente elas.
    2. Tier 2 (Alta Reputação): se não houver 500+, busca por 50+ avaliações e nota >= 4.0.
    3. Tier 3 (Produtos de Nicho/Específicos): se não houver 50+, busca por 5+ avaliações e nota >= 3.8.
    4. Tier 4 (Lançamentos/Poucas avaliações): se não houver 5+, exibe as opções mais baratas disponíveis com aviso.
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

    if not candidates:
        return [], False

    # Tier 1: Filtro anti-golpe estrito (500+ avaliações e nota satisfatória)
    tier1 = [
        o for o in candidates
        if o.reviews_count >= min_required_reviews and o.reliability_score >= min_acceptable_rating
    ]
    if tier1:
        tier1.sort(key=lambda o: (o.price, -o.reliability_score, -o.reviews_count))
        return tier1[:top_k], False

    # Tier 2: Boa reputação (50+ avaliações e nota >= 4.0)
    tier2 = [o for o in candidates if o.reviews_count >= 50 and o.rating >= 4.0]
    if tier2:
        tier2.sort(key=lambda o: (o.price, -o.reliability_score, -o.reviews_count))
        return tier2[:top_k], True

    # Tier 3: Produtos de nicho / específicos (5+ avaliações e nota >= 3.8)
    tier3 = [o for o in candidates if o.reviews_count >= 5 and o.rating >= 3.8]
    if tier3:
        tier3.sort(key=lambda o: (o.price, -o.reliability_score, -o.reviews_count))
        return tier3[:top_k], True

    # Tier 4: Produtos muito novos ou lançamentos com poucas avaliações registradas
    candidates.sort(key=lambda o: (o.price, -o.reliability_score, -o.reviews_count))
    return candidates[:top_k], True
