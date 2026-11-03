"""Gerenciamento do navegador Playwright com configurações que parecem um usuário comum."""

from __future__ import annotations

from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Playwright, async_playwright

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

# Esconde o sinal de automação (navigator.webdriver = true).
STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['pt-BR', 'pt', 'en-US', 'en'] });
"""

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

CONTEXT_OPTIONS = {
    "user_agent": USER_AGENT,
    "locale": "pt-BR",
    "timezone_id": "America/Sao_Paulo",
    "viewport": {"width": 1366, "height": 768},
    "extra_http_headers": {"Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
}

PROFILES_DIR = Path(__file__).resolve().parent.parent / ".browser_profiles"


class BrowserManager:
    """Abre um único navegador compartilhado; cada loja recebe seu próprio contexto (aba isolada)."""

    def __init__(self, headless: bool = True, use_chrome: bool = False):
        self.headless = headless
        # channel="chrome" usa o Google Chrome instalado, que é menos detectado que o Chromium.
        self.channel = "chrome" if use_chrome else None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> "BrowserManager":
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless, channel=self.channel, args=LAUNCH_ARGS
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def new_context(self, user_agent: str | None = None) -> BrowserContext:
        assert self._browser, "Use BrowserManager dentro de 'async with'."
        opts = dict(CONTEXT_OPTIONS)
        if user_agent:
            opts["user_agent"] = user_agent
        context = await self._browser.new_context(**opts)
        await context.add_init_script(STEALTH_SCRIPT)
        return context

    async def persistent_context(self, profile_name: str, headless: bool | None = None) -> BrowserContext:
        """Contexto com perfil salvo em disco (cookies/login persistem entre execuções)."""
        assert self._playwright, "Use BrowserManager dentro de 'async with'."
        profile_dir = PROFILES_DIR / profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)
        context = await self._playwright.chromium.launch_persistent_context(
            str(profile_dir),
            headless=self.headless if headless is None else headless,
            channel=self.channel,
            args=LAUNCH_ARGS,
            **CONTEXT_OPTIONS,
        )
        await context.add_init_script(STEALTH_SCRIPT)
        return context
