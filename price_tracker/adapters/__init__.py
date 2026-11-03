"""Registro central das 4 lojas monitoradas."""

from .amazon import AmazonAdapter
from .americanas import AmericanasAdapter
from .base import BaseStoreAdapter, StoreBlockedError
from .mercadolivre import MercadoLivreAdapter
from .shopee import ShopeeAdapter

ALL_ADAPTERS: dict[str, type[BaseStoreAdapter]] = {
    "mercadolivre": MercadoLivreAdapter,
    "amazon": AmazonAdapter,
    "americanas": AmericanasAdapter,
    "shopee": ShopeeAdapter,
}

__all__ = [
    "ALL_ADAPTERS",
    "BaseStoreAdapter",
    "StoreBlockedError",
    "MercadoLivreAdapter",
    "AmazonAdapter",
    "AmericanasAdapter",
    "ShopeeAdapter",
]
