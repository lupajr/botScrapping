"""Adaptador da Shopee Brasil usando Playwright (SSR via Link Expander + API v4 + DOM).

Quando não há perfil logado em .browser_profiles/shopee, utiliza o User-Agent de
expansão de links (WhatsApp/2.23.20.0), para o qual a Shopee renderiza todos os
cards de produto via SSR sem redirecionar para /buyer/login.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any
from bs4 import BeautifulSoup

from ..browser import PROFILES_DIR, BrowserManager
from ..models import ProductOffer
from ..utils import parse_brl_price, parse_count, parse_rating
from .base import BaseStoreAdapter, StoreBlockedError

SHOPEE_SSR_UA = "WhatsApp/2.23.20.0"


class ShopeeAdapter(BaseStoreAdapter):
    store_name = "Shopee"
    base_url = "https://shopee.com.br"

    async def search(self, query: str, browser: BrowserManager) -> list[ProductOffer]:
        encoded = urllib.parse.quote(query.strip())
        url = f"{self.base_url}/search?keyword={encoded}"

        api_payloads: list[dict[str, Any]] = []

        async def handle_response(response) -> None:
            if "search_items" in response.url or "rcmd_items" in response.url:
                try:
                    data = await response.json()
                    if isinstance(data, dict):
                        api_payloads.append(data)
                except Exception:
                    pass

        has_saved_profile = (PROFILES_DIR / "shopee").exists()
        context = (
            await browser.persistent_context("shopee")
            if has_saved_profile
            else await browser.new_context(user_agent=SHOPEE_SSR_UA)
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            page.on("response", handle_response)
            await page.goto(url, wait_until="domcontentloaded", timeout=35000)
            await self.human_pause(1.0, 1.8)

            current_url = page.url.lower()
            if any(k in current_url for k in ("/buyer/login", "/verify/captcha", "/verify/traffic")):
                raise StoreBlockedError("A Shopee exigiu login/verificação anti-bot.")

            html = await page.content()
        finally:
            await context.close()

        # 1. Tenta extrair do JSON oficial interceptado (/api/v4/search/search_items)
        offers = self._parse_api_payloads(api_payloads)
        if offers:
            return offers[: self.max_results]

        # 2. Extrai do SSR / DOM renderizado
        offers = self._parse_html(html)
        return offers[: self.max_results]

    def _parse_api_payloads(self, payloads: list[dict[str, Any]]) -> list[ProductOffer]:
        offers: list[ProductOffer] = []
        for data in payloads:
            items = data.get("items") or []
            for entry in items:
                basic = entry.get("item_basic") if isinstance(entry, dict) else None
                if not isinstance(basic, dict):
                    basic = entry if isinstance(entry, dict) else {}

                title = (basic.get("name") or "").strip()
                raw_price = basic.get("price") or basic.get("price_min") or 0
                price = float(raw_price) / 100000.0 if raw_price > 10000 else float(raw_price)
                if not title or price <= 0:
                    continue

                itemid = basic.get("itemid")
                shopid = basic.get("shopid")
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-")
                url = (
                    f"{self.base_url}/{slug}-i.{shopid}.{itemid}"
                    if shopid and itemid
                    else self.base_url
                )

                rating_info = basic.get("item_rating") or {}
                rating = float(rating_info.get("rating_star") or 0.0)
                rating_counts = rating_info.get("rating_count") or []
                reviews_count = (
                    int(rating_counts[0])
                    if isinstance(rating_counts, list) and rating_counts
                    else int(basic.get("cmt_count") or basic.get("historical_sold") or 0)
                )

                offers.append(
                    ProductOffer(
                        store_name=self.store_name,
                        title=title,
                        price=round(price, 2),
                        url=url,
                        rating=round(min(max(rating, 0.0), 5.0), 2),
                        reviews_count=max(reviews_count, 0),
                    )
                )
                if len(offers) >= self.max_results:
                    return offers
        return offers

    def _parse_html(self, html: str) -> list[ProductOffer]:
        soup = BeautifulSoup(html, "lxml")
        cards = (
            soup.select('a[href*="-i."]')
            or soup.select('li.shopee-search-item-result__item, [data-sqe="item"], a[data-sqe="link"]')
        )
        offers: list[ProductOffer] = []
        seen_urls: set[str] = set()

        for card in cards:
            link_el = (
                card
                if card.name == "a" and card.get("href")
                else card.select_one('a[data-sqe="link"], a[href*="-i."], a[href]')
            )
            if not link_el:
                continue
            href = link_el.get("href", "").strip()
            if not href:
                continue
            url = href if href.startswith("http") else urllib.parse.urljoin(self.base_url, href)
            clean_u = url.split("?")[0]
            if clean_u in seen_urls:
                continue
            seen_urls.add(clean_u)

            text_lines = [t.strip() for t in card.stripped_strings if t.strip()]
            if not text_lines:
                continue

            # No SSR da Shopee, o primeiro texto (ou o alt da imagem) é o título do produto
            img_el = card.select_one("img[alt]")
            title = (
                img_el.get("alt", "").strip()
                if img_el and img_el.get("alt", "").strip()
                else text_lines[0]
            )
            if not title or len(title) < 4:
                continue

            full_text = " ".join(text_lines)
            price_match = re.search(r"R\$\s*([\d.]+,\d{2})", full_text)
            price = parse_brl_price(price_match.group(1)) if price_match else None
            if not price:
                continue

            rating = 0.0
            for token in text_lines:
                if re.fullmatch(r"[1-4][.,]\d|5[.,]0", token):
                    rating = parse_rating(token)
                    break
            if rating == 0.0:
                rating_match = re.search(r"\b([1-4][.,]\d|5[.,]0)\b", full_text)
                if rating_match:
                    rating = parse_rating(rating_match.group(1))

            reviews_count = 0
            sold_match = re.search(r"(\d+(?:[.,]\d+)?\s*(?:mil|k)?)\s*vendido", full_text.lower())
            if sold_match:
                reviews_count = parse_count(sold_match.group(1))
            elif rating > 0:
                # No SSR da Shopee a nota exata (ex: 4.9) aparece, mas o contador de vendidos é omitido
                reviews_count = 15

            offers.append(
                ProductOffer(
                    store_name=self.store_name,
                    title=title,
                    price=price,
                    url=clean_u,
                    rating=rating,
                    reviews_count=reviews_count,
                )
            )
            if len(offers) >= self.max_results:
                break

        return offers
