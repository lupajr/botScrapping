"""Adaptador da Amazon Brasil usando Playwright + BeautifulSoup."""

from __future__ import annotations

import urllib.parse
from bs4 import BeautifulSoup

from ..browser import PROFILES_DIR, BrowserManager
from ..models import ProductOffer
from ..utils import parse_brl_price, parse_count, parse_rating
from .base import BaseStoreAdapter, StoreBlockedError


class AmazonAdapter(BaseStoreAdapter):
    store_name = "Amazon"
    base_url = "https://www.amazon.com.br"

    async def search(self, query: str, browser: BrowserManager) -> list[ProductOffer]:
        encoded = urllib.parse.quote_plus(query.strip())
        url = f"{self.base_url}/s?k={encoded}"

        has_saved_profile = (PROFILES_DIR / "amazon").exists()
        context = (
            await browser.persistent_context("amazon")
            if has_saved_profile
            else await browser.new_context()
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            await self.human_pause(1.2, 2.2)
            await self.scroll_page(page, steps=3)

            html = await page.content()
            if "validateCaptcha" in html or "Digite os caracteres que você vê" in html:
                raise StoreBlockedError(
                    "Amazon exibiu CAPTCHA anti-bot. Aguarde alguns minutos ou use --visivel / --chrome."
                )
        finally:
            await context.close()

        return self._parse_html(html)

    def _parse_html(self, html: str) -> list[ProductOffer]:
        soup = BeautifulSoup(html, "lxml")
        cards = soup.select('div[data-component-type="s-search-result"]')
        offers: list[ProductOffer] = []

        for card in cards:
            title_el = card.select_one("h2 span") or card.select_one("h2")
            if not title_el:
                continue
            title = title_el.get_text(" ", strip=True)
            if not title:
                continue

            asin = (card.get("data-asin") or "").strip()
            link_el = (
                card.select_one('a[href*="/dp/"]')
                or card.select_one("h2 a[href]")
                or card.select_one('a.a-link-normal.s-line-clamp-2[href]')
                or card.select_one('a.a-link-normal.s-no-outline[href]')
            )
            href = link_el.get("href", "").strip() if link_el else ""
            if "/sspa/click" in href and "url=" in href:
                parsed_qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                if "url" in parsed_qs and parsed_qs["url"]:
                    href = urllib.parse.unquote(parsed_qs["url"][0])
            if not href and asin:
                href = f"/dp/{asin}"
            if not href:
                continue
            url = href if href.startswith("http") else urllib.parse.urljoin(self.base_url, href)

            # Preço
            price: float | None = None
            offscreen_el = card.select_one(".a-price:not([data-a-strike]) .a-offscreen")
            if offscreen_el:
                price = parse_brl_price(offscreen_el.get_text(strip=True))
            if not price:
                whole_el = card.select_one(".a-price-whole")
                frac_el = card.select_one(".a-price-fraction")
                if whole_el:
                    raw = whole_el.get_text(strip=True).rstrip(",.")
                    if frac_el:
                        raw = f"{raw},{frac_el.get_text(strip=True)}"
                    price = parse_brl_price(raw)
            if not price:
                continue

            # Nota (ex: "4,7 de 5 estrelas")
            rating = 0.0
            rating_el = (
                card.select_one("span.a-icon-alt")
                or card.select_one("i[class*='star'] span")
                or card.select_one("span[aria-label*='estrela']")
            )
            if rating_el:
                rating_text = rating_el.get_text(" ", strip=True) or rating_el.get("aria-label", "")
                rating = parse_rating(rating_text)

            # Quantidade de avaliações
            reviews_count = 0
            reviews_el = (
                card.select_one("span.a-size-base.s-underline-text")
                or card.select_one("a[href*='#customerReviews'] span")
                or card.select_one("span[aria-label*='avalia']")
            )
            if reviews_el:
                rev_text = reviews_el.get_text(" ", strip=True) or reviews_el.get("aria-label", "")
                reviews_count = parse_count(rev_text)

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
