"""Envio de resultados formatados (Embeds) para o Discord via Webhook ou Bot."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

from .models import ProductOffer, StoreResult

STORE_COLORS = {
    "Amazon": 0xFF9900,         # Laranja Amazon
    "Mercado Livre": 0xFFE600,  # Amarelo ML
    "Americanas": 0xE60014,     # Vermelho Americanas
    "Shopee": 0xEE4D2D,         # Laranja Shopee
}


def load_env_file() -> dict[str, str]:
    """Lê variáveis do arquivo .env na raiz do projeto sem exigir dependências extras."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def get_webhook_url(explicit_url: str | None = None) -> str | None:
    if explicit_url:
        return explicit_url
    return os.environ.get("DISCORD_WEBHOOK_URL") or load_env_file().get("DISCORD_WEBHOOK_URL")


def format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_discord_embeds(
    query: str,
    top_offers: list[ProductOffer],
    results: list[StoreResult],
    used_fallback: bool = False,
) -> list[dict]:
    """Monta os cartões (Embeds) ricos do Discord com links clicáveis."""
    embeds: list[dict] = []

    for idx, offer in enumerate(top_offers, 1):
        medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(idx, f"#{idx}")
        embeds.append(
            {
                "title": f"{medal} {idx}º Lugar — [{offer.store_name}] {format_brl(offer.price)}",
                "url": offer.url,
                "description": (
                    f"**{offer.title}**\n\n"
                    f"⭐ **Nota:** {offer.rating:.1f}/5.0 ({offer.reviews_count} avaliações)\n"
                    f"🛡️ **Confiabilidade:** {offer.reliability_score:.2f}/5.0\n"
                    f"🛒 **[Clique aqui para abrir o produto na {offer.store_name}]({offer.url})**"
                ),
                "color": STORE_COLORS.get(offer.store_name, 0x2ECC71),
            }
        )

    store_lines = []
    for res in results:
        if res.error:
            store_lines.append(f"• **{res.store_name}:** indisponível ({res.elapsed_seconds:.1f}s)")
        else:
            store_lines.append(
                f"• **{res.store_name}:** {len(res.offers)} ofertas analisadas ({res.elapsed_seconds:.1f}s)"
            )

    footer_note = (
        "\n⚠️ *Nota: poucas ofertas tinham avaliações mínimas; exibindo as mais baratas disponíveis.*"
        if used_fallback
        else ""
    )

    embeds.append(
        {
            "title": "📊 Resumo da Varredura nas Lojas",
            "description": "\n".join(store_lines) + footer_note,
            "color": 0x3498DB,
        }
    )
    return embeds


def send_to_discord_webhook(
    query: str,
    top_offers: list[ProductOffer],
    results: list[StoreResult],
    used_fallback: bool = False,
    webhook_url: str | None = None,
    user_mention: str | None = None,
) -> None:
    """Envia o resultado do Top 3 para o canal do Discord configurado via Webhook."""
    target_url = get_webhook_url(webhook_url)
    if not target_url:
        raise ValueError("Nenhuma URL de Webhook do Discord configurada no arquivo .env.")

    ping_prefix = f"🔔 {user_mention}, sua pesquisa ficou pronta!\n" if user_mention else ""

    if not top_offers:
        payload = {
            "username": "Caçador de Preços 🛒",
            "content": (
                f"{ping_prefix}🔎 Busca por **`{query}`**: nenhuma oferta relevante foi encontrada."
            ),
            "allowed_mentions": {"parse": ["users"]},
        }
    else:
        payload = {
            "username": "Caçador de Preços 🛒",
            "content": (
                f"{ping_prefix}🔎 **Top {len(top_offers)} ofertas mais baratas e confiáveis para:** `{query}`"
            ),
            "embeds": build_discord_embeds(query, top_offers, results, used_fallback),
            "allowed_mentions": {"parse": ["users"]},
        }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        target_url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "PriceTrackerBot/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"Discord retornou status inesperado: {resp.status}")
