"""Adaptador do Mercado Livre usando Playwright + BeautifulSoup.

Utiliza User-Agent híbrido Chrome + WhatsApp In-App para que o Mercado Livre execute
o desafio automático de Proof-of-Work ( ~6s ) em vez de exigir login (account-verification).
"""

from __future__ import annotations

import urllib.parse
from bs4 import BeautifulSoup

from ..browser import PROFILES_DIR, BrowserManager
from ..models import ProductOffer
from ..utils import parse_brl_price, parse_count, parse_rating
from .base import BaseStoreAdapter, StoreBlockedError

ML_INAPP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 WhatsApp/2.24.22"
)


class MercadoLivreAdapter(BaseStoreAdapter):
    store_name = "Mercado Livre"

    async def search(self, query: str, browser: BrowserManager) -> list[ProductOffer]:
        slug = urllib.parse.quote(query.strip().replace(" ", "-"))
        direct_url = f"https://lista.mercadolivre.com.br/{slug}"

        has_saved_profile = (PROFILES_DIR / "mercadolivre").exists()
        context = (
            await browser.persistent_context("mercadolivre")
            if has_saved_profile
            else await browser.new_context(user_agent=ML_INAPP_UA)
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(direct_url, wait_until="domcontentloaded", timeout=35000)

            # Aguarda o desafio automático de Proof-of-Work (_bmstate -> _bmc) concluir
            # e carregar os cards reais na página (~5 a 8 segundos).
            for _ in range(14):
                await page.wait_for_timeout(1000)
                if any(k in page.url for k in ("account-verification", "/login", "/captcha/wall")):
                    raise StoreBlockedError(
                        "Mercado Livre solicitou verificação de conta."
                    )
                try:
                    cnt = await page.locator(
                        "li.ui-search-layout__item, div.poly-card"
                    ).count()
                    if cnt > 0:
                        break
                except Exception:
                    # Página pode estar navegando após concluir o PoW
                    continue

            await self.scroll_page(page, steps=3)
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            html = await page.content()
        finally:
            await context.close()

        return self._parse_html(html)

    def _parse_html(self, html: str) -> list[ProductOffer]:
        soup = BeautifulSoup(html, "lxml")
        cards = (
            soup.select("li.ui-search-layout__item")
            or soup.select("div.poly-card")
            or soup.select("div.ui-search-result__wrapper")
        )
        offers: list[ProductOffer] = []
        seen_urls: set[str] = set()

        for card in cards:
            title_el = card.select_one(
                "a.poly-component__title, h2.poly-box, h2.ui-search-item__title, "
                ".poly-component__title"
            )
            if not title_el:
                continue
            title = title_el.get_text(" ", strip=True)

            link_el = (
                title_el
                if title_el.name == "a" and title_el.get("href")
                else card.select_one(
                    "a.poly-component__title, a.ui-search-link, a.ui-search-item__group__element, a[href]"
                )
            )
            url = link_el.get("href", "").strip() if link_el else ""
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            # Preço atual (ignora preço antigo riscado <s>)
            price_container = card.select_one(
                ".poly-price__current, .ui-search-price__second-line, .andes-money-amount--cents-superscript"
            ) or card
            fraction_el = price_container.select_one(".andes-money-amount__fraction")
            cents_el = price_container.select_one(".andes-money-amount__cents")
            if not fraction_el:
                continue

            raw_price = fraction_el.get_text(strip=True)
            if cents_el:
                raw_price = f"{raw_price},{cents_el.get_text(strip=True)}"
            price = parse_brl_price(raw_price)
            if not price:
                continue

            rating_el = card.select_one(
                ".poly-reviews__rating, .ui-search-reviews__rating-number, "
                "span.andes-visually-hidden"
            )
            rating = parse_rating(rating_el.get_text(" ", strip=True)) if rating_el else 0.0

            reviews_el = card.select_one(
                ".poly-reviews__total, .ui-search-reviews__amount"
            )
            reviews_count = parse_count(reviews_el.get_text(" ", strip=True)) if reviews_el else 0

            offers.append(
                ProductOffer(
                    store_name=self.store_name,
                    title=title,
                    price=price,
                    url=url,
                    rating=rating,
                    reviews_count=reviews_count,
                )
            )
            if len(offers) >= self.max_results:
                break

        return offers
