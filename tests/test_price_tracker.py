"""Testes unitários do pesquisador de preços (parsers, média bayesiana e ranqueamento)."""

from __future__ import annotations

import unittest

from price_tracker.adapters.amazon import AmazonAdapter
from price_tracker.adapters.americanas import AmericanasAdapter
from price_tracker.adapters.mercadolivre import MercadoLivreAdapter
from price_tracker.adapters.shopee import ShopeeAdapter
from price_tracker.models import ProductOffer
from price_tracker.scorer import (
    compute_bayesian_rating,
    extract_category_from_text,
    rank_top_cheapest_and_reliable,
)
from price_tracker.utils import parse_brl_price, parse_count, parse_rating


class TestUtilsAndScorer(unittest.TestCase):
    def test_parse_brl_price(self):
        self.assertEqual(parse_brl_price("R$ 1.234,56"), 1234.56)
        self.assertEqual(parse_brl_price("299,90"), 299.90)
        self.assertEqual(parse_brl_price("1.500"), 1500.0)
        self.assertIsNone(parse_brl_price("Grátis"))

    def test_parse_rating_and_count(self):
        self.assertEqual(parse_rating("4,8 de 5 estrelas"), 4.8)
        self.assertEqual(parse_count("(1.450)"), 1450)
        self.assertEqual(parse_count("2,5 mil avaliações"), 2500)

    def test_bayesian_rating_prevents_one_review_distortion(self):
        score_one_review = compute_bayesian_rating(5.0, 1)
        score_many_reviews = compute_bayesian_rating(4.7, 1500)
        self.assertGreater(score_many_reviews, score_one_review)

    def test_rank_top_3_cheapest_and_reliable(self):
        offers = [
            ProductOffer(
                store_name="Mercado Livre",
                title="Fone Bluetooth JBL Tune 520BT Preto",
                price=180.0,
                url="https://mercadolivre.com.br/p/1",
                rating=5.0,
                reviews_count=1,  # Poucas avaliações -> deve ser filtrado
            ),
            ProductOffer(
                store_name="Amazon",
                title="Fone de Ouvido Bluetooth JBL Tune 520BT",
                price=219.90,
                url="https://amazon.com.br/dp/1",
                rating=4.8,
                reviews_count=3420,
            ),
            ProductOffer(
                store_name="Shopee",
                title="Fone Bluetooth JBL Tune 520BT Original",
                price=209.00,
                url="https://shopee.com.br/item/2",
                rating=4.7,
                reviews_count=520,
            ),
            ProductOffer(
                store_name="Americanas",
                title="Fone Bluetooth JBL Tune 520BT Azul",
                price=235.00,
                url="https://americanas.com.br/produto/3",
                rating=4.6,
                reviews_count=85,
            ),
            ProductOffer(
                store_name="Mercado Livre",
                title="Capinha Case Para Fone JBL",  # Irrelevante (falta 'bluetooth')
                price=25.00,
                url="https://mercadolivre.com.br/p/case",
                rating=4.9,
                reviews_count=200,
            ),
        ]

        top_3, used_fallback = rank_top_cheapest_and_reliable(
            offers, query="fone bluetooth jbl", top_k=3
        )
        self.assertFalse(used_fallback)
        self.assertEqual(len(top_3), 3)
        self.assertEqual([o.store_name for o in top_3], ["Shopee", "Amazon", "Americanas"])
        self.assertEqual([o.price for o in top_3], [209.00, 219.90, 235.00])

    def test_category_extraction_and_accessory_filtering(self):
        prod, cat = extract_category_from_text("nintendo Switch OLED video games")
        self.assertEqual(prod, "nintendo Switch OLED")
        self.assertEqual(cat, "videogames")

        prod_acc, cat_acc = extract_category_from_text("nintendo Switch OLED acessorios")
        self.assertEqual(prod_acc, "nintendo Switch OLED")
        self.assertEqual(cat_acc, "acessorios")

        switch_offers = [
            ProductOffer(
                store_name="Amazon",
                title="Pelicula De Vidro Protetor para Nintendo Switch Oled",
                price=22.85,
                url="https://amazon.com.br/dp/1",
                rating=4.7,
                reviews_count=440,
            ),
            ProductOffer(
                store_name="Amazon",
                title="Case Compatível com Nintendo Switch OLED e Lite EVA Rígido Porta 10 Jogos",
                price=42.62,
                url="https://amazon.com.br/dp/2",
                rating=4.6,
                reviews_count=123,
            ),
            ProductOffer(
                store_name="Amazon",
                title="Console Nintendo Switch OLED Branco - Nacional",
                price=2199.00,
                url="https://amazon.com.br/dp/3",
                rating=4.9,
                reviews_count=3200,
            ),
        ]

        # Na categoria videogames (ou geral), películas e cases são descartados e só fica o Console!
        top_console, _ = rank_top_cheapest_and_reliable(
            switch_offers, query="Nintendo Switch OLED", category="videogames"
        )
        self.assertEqual(len(top_console), 1)
        self.assertEqual(top_console[0].price, 2199.00)

        # Na categoria acessorios, as películas e cases são permitidos!
        top_acc, _ = rank_top_cheapest_and_reliable(
            switch_offers, query="Nintendo Switch OLED", category="acessorios"
        )
        self.assertEqual(top_acc[0].price, 22.85)


class TestStoreParsers(unittest.TestCase):
    def test_mercadolivre_parser(self):
        html = """
        <li class="ui-search-layout__item">
          <div class="poly-card">
            <a class="poly-component__title" href="https://produto.mercadolivre.com.br/MLB-1">
              Fone Bluetooth JBL Tune 520BT
            </a>
            <div class="poly-price__current">
              <span class="andes-money-amount__fraction">229</span>
              <span class="andes-money-amount__cents">90</span>
            </div>
            <span class="poly-reviews__rating">4.8</span>
            <span class="poly-reviews__total">(1.230)</span>
          </div>
        </li>
        """
        offers = MercadoLivreAdapter()._parse_html(html)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 229.90)
        self.assertEqual(offers[0].rating, 4.8)
        self.assertEqual(offers[0].reviews_count, 1230)

    def test_amazon_parser(self):
        html = """
        <div data-component-type="s-search-result">
          <h2><a href="/dp/B09V3KXJPB"><span>Fone Bluetooth JBL Tune 520BT</span></a></h2>
          <span class="a-price"><span class="a-offscreen">R$ 215,50</span></span>
          <i class="a-icon-star-small"><span class="a-icon-alt">4,7 de 5 estrelas</span></i>
          <span class="a-size-base s-underline-text">980</span>
        </div>
        """
        offers = AmazonAdapter()._parse_html(html)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 215.50)
        self.assertEqual(offers[0].rating, 4.7)
        self.assertEqual(offers[0].reviews_count, 980)

    def test_americanas_json_ld_parser(self):
        html = """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Fone Bluetooth JBL Tune 520BT",
          "url": "https://www.americanas.com.br/produto/12345",
          "offers": {"lowPrice": 239.99},
          "aggregateRating": {"ratingValue": 4.6, "reviewCount": 74}
        }
        </script>
        """
        offers = AmericanasAdapter()._parse_html(html)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 239.99)
        self.assertEqual(offers[0].rating, 4.6)
        self.assertEqual(offers[0].reviews_count, 74)

    def test_shopee_api_parser(self):
        payload = [
            {
                "items": [
                    {
                        "item_basic": {
                            "name": "Fone Bluetooth JBL Tune 520BT",
                            "price": 19990000,
                            "itemid": 111,
                            "shopid": 222,
                            "item_rating": {"rating_star": 4.85, "rating_count": [310]},
                        }
                    }
                ]
            }
        ]
        offers = ShopeeAdapter()._parse_api_payloads(payload)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0].price, 199.90)
        self.assertEqual(offers[0].rating, 4.85)
        self.assertEqual(offers[0].reviews_count, 310)


if __name__ == "__main__":
    unittest.main()
