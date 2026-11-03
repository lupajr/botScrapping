"""Linha de comando do pesquisador de preços.

Exemplos:
    python -m price_tracker "fone bluetooth jbl"
    python -m price_tracker "monitor 24 144hz" --lojas amazon mercadolivre --json resultado.json
    python -m price_tracker --login shopee
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import webbrowser

from .adapters import ALL_ADAPTERS
from .browser import BrowserManager
from .discord_notifier import send_to_discord_webhook
from .engine import search_all_stores
from .scorer import (
    CATEGORY_RULES,
    build_store_search_query,
    extract_category_from_text,
    rank_top_cheapest_and_reliable,
    resolve_category,
)

LOGIN_URLS = {
    "shopee": "https://shopee.com.br/buyer/login",
    "amazon": "https://www.amazon.com.br/",
    "mercadolivre": "https://www.mercadolivre.com.br/",
    "americanas": "https://www.americanas.com.br/",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="price_tracker",
        description="Busca um produto em várias lojas e mostra as opções mais baratas e confiáveis.",
    )
    parser.add_argument("produto", nargs="?", help="Nome do produto a pesquisar")
    parser.add_argument(
        "--categoria",
        choices=list(CATEGORY_RULES),
        help="Categoria desejada (ex: videogames, controles, jogos, celulares, informatica, acessorios)",
    )
    parser.add_argument(
        "--lojas", nargs="+", choices=list(ALL_ADAPTERS), help="Lojas a consultar (padrão: todas)"
    )
    parser.add_argument("--top", type=int, default=3, help="Quantidade de ofertas no ranking")
    parser.add_argument("--min-avaliacoes", type=int, default=5, help="Mínimo de avaliações")
    parser.add_argument("--nota-minima", type=float, default=3.8, help="Nota ponderada mínima (0-5)")
    parser.add_argument("--preco-min", type=float, help="Ignora ofertas abaixo deste preço")
    parser.add_argument("--preco-max", type=float, help="Ignora ofertas acima deste preço")
    parser.add_argument("--timeout", type=float, default=90, help="Tempo máximo por loja (s)")
    parser.add_argument("--visivel", action="store_true", help="Mostra o navegador (útil p/ depurar)")
    parser.add_argument("--chrome", action="store_true", help="Usa o Google Chrome instalado")
    parser.add_argument(
        "--abrir",
        action="store_true",
        help="Abre automaticamente os links do Top 3 no seu navegador padrão",
    )
    parser.add_argument(
        "--discord",
        action="store_true",
        help="Envia o resultado do Top 3 diretamente para o seu canal do Discord (via Webhook)",
    )
    parser.add_argument("--json", metavar="ARQUIVO", help="Salva o resultado completo em JSON")
    parser.add_argument(
        "--login",
        choices=list(LOGIN_URLS),
        help="Abre o navegador para você fazer login na loja (o login fica salvo)",
    )
    return parser


async def interactive_login(store: str, use_chrome: bool) -> None:
    async with BrowserManager(headless=False, use_chrome=use_chrome) as browser:
        context = await browser.persistent_context(store, headless=False)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(LOGIN_URLS[store])
        print(f"Faça login na {store} na janela aberta e depois FECHE a janela do navegador.")
        await context.wait_for_event("close", timeout=0)
    print("Login salvo em .browser_profiles/" + store)


def print_report(query: str, results, top, used_fallback) -> None:
    print("\n" + "=" * 70)
    print(f"Resumo da busca por: {query!r}")
    print("=" * 70)
    for res in results:
        status = f"{len(res.offers)} ofertas" if not res.error else f"FALHOU -> {res.error}"
        print(f"  - {res.store_name:<14} {status}  ({res.elapsed_seconds:.1f}s)")

    print("\n" + "=" * 70)
    print(f"TOP {len(top)} - MAIS BARATOS E CONFIÁVEIS")
    print("=" * 70)
    if not top:
        print("Nenhuma oferta relevante encontrada. Tente termos mais genéricos.")
        return
    if used_fallback:
        print("[!] Não há ofertas confiáveis suficientes; algumas abaixo têm poucas avaliações.\n")
    for i, item in enumerate(top, 1):
        price_brl = f"{item.price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        print(f"{i}. [{item.store_name}] R$ {price_brl}")
        print(f"   Produto:   {item.title[:110]}")
        print(
            f"   Avaliação: {item.rating:.1f}★ ({item.reviews_count} avaliações)"
            f" | Confiabilidade: {item.reliability_score:.2f}/5"
        )
        print(f"   Link:      {item.url}\n")


def main(argv: list[str] | None = None) -> int:
    # Garante acentos e ★ corretos no terminal do Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)

    if args.login:
        asyncio.run(interactive_login(args.login, args.chrome))
        return 0
    if not args.produto:
        build_parser().error("informe o nome do produto (ou use --login)")

    clean_prod, detected_cat = extract_category_from_text(args.produto)
    category = args.categoria or detected_cat
    if category and not args.categoria:
        args.produto = clean_prod

    rule = resolve_category(category)
    store_query = build_store_search_query(args.produto, category=category)
    lojas = args.lojas or list(ALL_ADAPTERS)
    print(
        f"[*] Buscando {args.produto!r} (Categoria: {rule.label} | Busca na loja: {store_query!r}) "
        f"em {len(lojas)} lojas: {', '.join(lojas)} ..."
    )
    results = asyncio.run(
        search_all_stores(
            store_query,
            stores=lojas,
            headless=not args.visivel,
            use_chrome=args.chrome,
            timeout=args.timeout,
        )
    )

    all_offers = [offer for res in results for offer in res.offers]
    top, used_fallback = rank_top_cheapest_and_reliable(
        all_offers,
        query=args.produto,
        top_k=args.top,
        min_required_reviews=args.min_avaliacoes,
        min_acceptable_rating=args.nota_minima,
        min_price=args.preco_min,
        max_price=args.preco_max,
        category=category,
    )
    print_report(args.produto, results, top, used_fallback)

    if args.abrir and top:
        print("[*] Abrindo os links do Top 3 no navegador...")
        for item in top:
            webbrowser.open(item.url)

    if args.discord:
        print("[*] Enviando resultado para o canal do Discord...")
        send_to_discord_webhook(args.produto, top, results, used_fallback=used_fallback)
        print("[*] Mensagem enviada com sucesso para o Discord!")

    if args.json:
        payload = {
            "query": args.produto,
            "top": [o.model_dump() for o in top],
            "stores": [r.model_dump() for r in results],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"[*] Resultado completo salvo em {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
