"""Interface comum que todo adaptador de loja implementa."""

from __future__ import annotations

import asyncio
import random
from abc import ABC, abstractmethod

from ..browser import BrowserManager
from ..models import ProductOffer


class StoreBlockedError(RuntimeError):
    """A loja exibiu CAPTCHA, verificação ou exigiu login."""


class BaseStoreAdapter(ABC):
    store_name: str = "Loja"
    max_results: int = 30

    @abstractmethod
    async def search(self, query: str, browser: BrowserManager) -> list[ProductOffer]:
        """Realiza a busca na loja e retorna ofertas estruturadas."""

    @staticmethod
    async def human_pause(min_s: float = 0.8, max_s: float = 2.0) -> None:
        """Pausa aleatória para não sobrecarregar o site e parecer navegação humana."""
        await asyncio.sleep(random.uniform(min_s, max_s))

    @staticmethod
    async def scroll_page(page, steps: int = 4) -> None:
        """Rola a página para disparar o carregamento preguiçoso (lazy load) dos produtos."""
        for _ in range(steps):
            await page.mouse.wheel(0, 1500)
            await asyncio.sleep(random.uniform(0.4, 0.9))
