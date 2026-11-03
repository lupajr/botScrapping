"""Orquestrador: dispara as buscas em todas as lojas em paralelo e consolida os resultados."""

from __future__ import annotations

import asyncio
import time

from .adapters import ALL_ADAPTERS
from .adapters.base import BaseStoreAdapter
from .browser import BrowserManager
from .models import StoreResult


async def _run_adapter(
    adapter: BaseStoreAdapter, query: str, browser: BrowserManager, timeout: float
) -> StoreResult:
    """Executa uma loja isolada: se ela falhar ou travar, as outras continuam."""
    start = time.perf_counter()
    try:
        offers = await asyncio.wait_for(adapter.search(query, browser), timeout=timeout)
        return StoreResult(
            store_name=adapter.store_name,
            offers=offers,
            elapsed_seconds=time.perf_counter() - start,
        )
    except asyncio.TimeoutError:
        error = f"tempo esgotado ({timeout:.0f}s)"
    except Exception as exc:  # noqa: BLE001 - queremos capturar qualquer falha da loja
        error = f"{type(exc).__name__}: {exc}"
    return StoreResult(
        store_name=adapter.store_name, error=error, elapsed_seconds=time.perf_counter() - start
    )


async def search_all_stores(
    query: str,
    stores: list[str] | None = None,
    headless: bool = True,
    use_chrome: bool = False,
    timeout: float = 60.0,
) -> list[StoreResult]:
    selected = stores or list(ALL_ADAPTERS)
    adapters = [ALL_ADAPTERS[key]() for key in selected]

    async with BrowserManager(headless=headless, use_chrome=use_chrome) as browser:
        tasks = [_run_adapter(a, query, browser, timeout) for a in adapters]
        return await asyncio.gather(*tasks)
