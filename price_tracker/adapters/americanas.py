"""Adaptador da Americanas usando Playwright (Interceptação JSON + DOM + JSON-LD)."""

from __future__ import annotations

import json
import urllib.parse
from typing import Any
from bs4 import BeautifulSoup

from ..browser import PROFILES_DIR, BrowserManager
from ..models import ProductOffer
from ..utils import parse_brl_price, parse_count, parse_rating
from .base import BaseStoreAdapter, StoreBlockedError


class AmericanasAdapter(BaseStoreAdapter):
    store_name = "Americanas"
    base_url = "https://www.americanas.com.br"

    async def search(self, query: str, browser: BrowserManager) -> list[ProductOffer]:
        slug = urllib.parse.quote(query.strip().replace(" ", "-"))
        url = f"{self.base_url}/busca/{slug}"

        captured_payloads: list[Any] = []

        async def handle_response(response) -> None:
            ct = response.headers.get("content-type", "")
            if "json" in ct and any(
                k in response.url.lower() for k in ("graphql", "search", "busca", "product")
            ):
                try:
                    data = await response.json()
                    captured_payloads.append(data)
                except Exception:
                    pass

        has_saved_profile = (PROFILES_DIR / "americanas").exists()
        context = (
            await browser.persistent_context("americanas")
            if has_saved_profile
            else await browser.new_context()
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            page.on("response", handle_response)
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await self.human_pause(1.5, 2.5)
            await self.scroll_page(page, steps=4)

            html = await page.content()
            if "Access Denied" in html or "Attention Required! | Cloudflare" in html:
                raise StoreBlockedError(
                    "Americanas bloqueou a requisição automatizada (Cloudflare/Akamai). "
                    "Tente executar com --visivel ou --chrome."
                )
        finally:
            await context.close()

        offers: list[ProductOffer] = []

        # 1. Tenta extrair via JSON interceptado / __NEXT_DATA__ / JSON-LD
        for payload in captured_payloads:
            self._extract_from_json(payload, offers)
            if len(offers) >= self.max_results:
                return offers[: self.max_results]

        # 2. Tenta extrair via HTML (JSON-LD e cards de produto)
        dom_offers = self._parse_html(html)
        seen_urls = {o.url for o in offers}
        for offer in dom_offers:
            if offer.url not in seen_urls:
                offers.append(offer)
                seen_urls.add(offer.url)
            if len(offers) >= self.max_results:
                break

        return offers

    def _extract_from_json(self, node: Any, out: list[ProductOffer]) -> None:
        """Percorre recursivamente estruturas GraphQL/FastStore procurando objetos de produto."""
        if len(out) >= self.max_results:
            return
        if isinstance(node, dict):
            # Formato VTEX / FastStore / B2W
            name = node.get("name") or node.get("productName")
            slug = node.get("slug") or node.get("linkText")
            offers_node = node.get("offers")
            if isinstance(name, str) and (slug or isinstance(offers_node, dict)):
                price = None
                if isinstance(offers_node, dict):
                    price = offers_node.get("lowPrice") or offers_node.get("price")
                    if not price and isinstance(offers_node.get("offers"), list) and offers_node["offers"]:
                        price = offers_node["offers"][0].get("price")
                if not price:
                    price = node.get("price") or node.get("salesPrice")
                if isinstance(price, (int, float)) and price > 0:
                    url = node.get("url") or (f"{self.base_url}/produto/{slug}" if slug else "")
                    if url and not url.startswith("http"):
                        url = urllib.parse.urljoin(self.base_url, url)
                    rating = 0.0
                    reviews = 0
                    agg = node.get("aggregateRating") or node.get("rating")
                    if isinstance(agg, dict):
                        rating = float(agg.get("ratingValue") or agg.get("average") or 0.0)
                        reviews = int(agg.get("reviewCount") or agg.get("count") or 0)
                    if url:
                        out.append(
                            ProductOffer(
                                store_name=self.store_name,
                                title=name.strip(),
                                price=float(price),
                                url=url,
                                rating=min(max(rating, 0.0), 5.0),
                                reviews_count=max(reviews, 0),
                            )
                        )
                        return

            for val in node.values():
                self._extract_from_json(val, out)
        elif isinstance(node, list):
            for item in node:
                self._extract_from_json(item, out)

    def _parse_html(self, html: str) -> list[ProductOffer]:
        soup = BeautifulSoup(html, "lxml")
        offers: list[ProductOffer] = []

        # 2a. JSON-LD (Schema.org ItemList / Product)
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
                self._extract_from_json(data, offers)
            except Exception:
                continue

        # 2b. __NEXT_DATA__
        next_data = soup.select_one("script#__NEXT_DATA__")
        if next_data and next_data.string:
            try:
                self._extract_from_json(json.loads(next_data.string), offers)
            except Exception:
                pass

        if offers:
            return offers[: self.max_results]

        # 2c. Seletores DOM de cards de produto
        cards = soup.select(
            '[data-fs-product-card], [class*="product-card"], [class*="ProductCard"], '
            'div[class*="inStockCard"]'
        )
        if not cards:
            cards = [a.parent for a in soup.select('a[href*="/produto/"]') if a.parent]

        for card in cards:
            link_el = (
                card if getattr(card, "name", None) == "a" and card.get("href")
                else card.select_one('a[href*="/produto/"], a[href]')
            )
            if not link_el:
                continue
            href = link_el.get("href", "").strip()
            if not href:
                continue
            url = href if href.startswith("http") else urllib.parse.urljoin(self.base_url, href)

            title_el = card.select_one(
                'h2, h3, [class*="product-name"], [class*="ProductName"], [data-fs-product-card-title]'
            ) or link_el
            title = title_el.get_text(" ", strip=True) if title_el else ""
            if not title or len(title) < 4:
                continue

            price_el = card.select_one(
                '[data-fs-price], [class*="price"], [class*="Price"], [class*="sales-price"]'
            )
            price = parse_brl_price(price_el.get_text(" ", strip=True)) if price_el else None
            if not price:
                continue

            rating_el = card.select_one('[class*="rating"], [aria-label*="estrela"]')
            rating = parse_rating(rating_el.get_text(" ", strip=True)) if rating_el else 0.0

            rev_el = card.select_one('[class*="review"], [class*="count"]')
            reviews_count = parse_count(rev_el.get_text(" ", strip=True)) if rev_el else 0

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
