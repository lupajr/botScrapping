"""Bot interativo do Discord para responder ao comando /preco ou !preco no chat.

Suporta filtro inteligente de categorias (ex: '/preco Nintendo Switch OLED video games'
ou '/preco Nintendo Switch OLED acessorios') e menciona (@usuario) ao término do scraping.
"""

from __future__ import annotations

import asyncio
import os
import sys
import discord
from discord import app_commands
from discord.ext import commands

from .discord_notifier import build_discord_embeds, load_env_file
from .engine import search_all_stores
from .scorer import (
    build_store_search_query,
    extract_category_from_text,
    rank_top_cheapest_and_reliable,
    resolve_category,
)


def get_bot_token() -> str:
    token = os.environ.get("DISCORD_BOT_TOKEN") or load_env_file().get("DISCORD_BOT_TOKEN", "")
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN não encontrado no arquivo .env!")
    return token


async def run_price_search(
    raw_input: str,
    explicit_category: str | None = None,
    min_reviews: int = 500,
):
    clean_prod, detected_cat = extract_category_from_text(raw_input)
    category = explicit_category or detected_cat
    produto = clean_prod if (detected_cat and not explicit_category) else raw_input.strip()

    rule = resolve_category(category)
    store_query = build_store_search_query(produto, category=category)

    results = await search_all_stores(store_query, headless=True, timeout=60.0)
    all_offers = [offer for res in results for offer in res.offers]
    top, used_fallback = rank_top_cheapest_and_reliable(
        all_offers,
        query=produto,
        top_k=3,
        min_required_reviews=min_reviews,
        category=category,
    )
    return produto, rule, top, results, used_fallback


CATEGORY_CHOICES = [
    app_commands.Choice(name="🎮 Video Games / Consoles", value="videogames"),
    app_commands.Choice(name="🕹️ Controles / Gamepads", value="controles"),
    app_commands.Choice(name="💿 Jogos / Games", value="jogos"),
    app_commands.Choice(name="📱 Celulares / Smartphones", value="celulares"),
    app_commands.Choice(name="💻 Informática / Hardware", value="informatica"),
    app_commands.Choice(name="🎒 Acessórios (Capas, Películas, Cases, Cabos)", value="acessorios"),
    app_commands.Choice(name="📦 Geral (Sem Acessórios)", value="geral"),
]

SECURITY_CHOICES = [
    app_commands.Choice(name="🛡️ 500+ avaliações (Padrão Anti-Golpe)", value=500),
    app_commands.Choice(name="🔒 1.000+ avaliações (Máxima Segurança)", value=1000),
]


def create_bot(enable_message_content: bool = True) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = enable_message_content

    bot = commands.Bot(command_prefix=("!", "/"), intents=intents)

    @bot.event
    async def on_ready() -> None:
        print(f"[*] Bot conectado como {bot.user} (ID: {bot.user.id if bot.user else '?'})")
        for guild in bot.guilds:
            try:
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
                print(f"[*] Comando /preco sincronizado no servidor: {guild.name} ({guild.id})")
            except Exception as exc:
                print(f"[!] Falha ao sincronizar no servidor {guild.name}: {exc}")
        try:
            await bot.tree.sync()
        except Exception:
            pass
        print("[*] Pronto para receber /preco no Discord!")

    @bot.event
    async def on_guild_join(guild: discord.Guild) -> None:
        try:
            bot.tree.copy_global_to(guild=guild)
            await bot.tree.sync(guild=guild)
            print(f"[*] Bot adicionado e /preco sincronizado no servidor: {guild.name}")
        except Exception as exc:
            print(f"[!] Erro ao sincronizar em novo servidor {guild.name}: {exc}")

    @bot.tree.command(
        name="preco",
        description="Busca as 3 opções mais baratas e confiáveis (500+ avaliações) e te avisa quando terminar",
    )
    @app_commands.describe(
        produto="Nome do produto (ex: Nintendo Switch OLED, ou 'Nintendo Switch OLED video games')",
        categoria="Categoria desejada (opcional: filtra consoles, controles, acessórios, etc.)",
        min_avaliacoes="Filtro anti-golpe de avaliações mínimas (padrão: 500+ avaliações)",
    )
    @app_commands.choices(categoria=CATEGORY_CHOICES, min_avaliacoes=SECURITY_CHOICES)
    async def slash_preco(
        interaction: discord.Interaction,
        produto: str,
        categoria: app_commands.Choice[str] | None = None,
        min_avaliacoes: app_commands.Choice[int] | None = None,
    ) -> None:
        user_mention = interaction.user.mention
        explicit_cat = categoria.value if categoria else None
        min_rev = min_avaliacoes.value if min_avaliacoes else 500
        clean_prod, detected_cat = extract_category_from_text(produto)
        preview_rule = resolve_category(explicit_cat or detected_cat)
        preview_prod = clean_prod if (detected_cat and not explicit_cat) else produto.strip()

        await interaction.response.send_message(
            f"🔎 {user_mention}, iniciei a busca por **`{preview_prod}`** "
            f"(📂 **{preview_rule.label}** | 🛡️ Anti-Golpe: **{min_rev}+ avaliações**)!\n"
            f"Vou te marcar assim que terminar (~12 segundos)..."
        )

        final_prod, rule, top, results, used_fallback = await run_price_search(
            produto, explicit_category=explicit_cat, min_reviews=min_rev
        )
        allowed = discord.AllowedMentions(users=True)

        if not top:
            msg = (
                f"🔔 {user_mention}, a busca por **`{final_prod}`** "
                f"(📂 **{rule.label}**) terminou, mas nenhuma oferta relevante foi encontrada."
            )
            if interaction.channel and hasattr(interaction.channel, "send"):
                await interaction.channel.send(content=msg, allowed_mentions=allowed)
            else:
                await interaction.followup.send(content=msg, allowed_mentions=allowed)
            return

        raw_embeds = build_discord_embeds(final_prod, top, results, used_fallback)
        discord_embeds = [discord.Embed.from_dict(e) for e in raw_embeds]
        msg = (
            f"🔔 {user_mention}, sua pesquisa ficou pronta!\n"
            f"🔎 **Top {len(top)} ofertas mais baratas e confiáveis para:** `{final_prod}` "
            f"*(📂 {rule.label})*"
        )
        if interaction.channel and hasattr(interaction.channel, "send"):
            await interaction.channel.send(
                content=msg, embeds=discord_embeds, allowed_mentions=allowed
            )
        else:
            await interaction.followup.send(
                content=msg, embeds=discord_embeds, allowed_mentions=allowed
            )

    @bot.command(name="preco")
    async def text_preco(ctx: commands.Context, *, produto: str) -> None:
        """Permite digitar !preco <produto> [categoria] ou /preco <produto> [categoria] no chat."""
        user_mention = ctx.author.mention
        clean_prod, detected_cat = extract_category_from_text(produto)
        preview_rule = resolve_category(detected_cat)

        await ctx.reply(
            f"🔎 {user_mention}, buscando **`{clean_prod}`** "
            f"(📂 Categoria: **{preview_rule.label}**) nas lojas... Te aviso assim que terminar!"
        )
        final_prod, rule, top, results, used_fallback = await run_price_search(produto)
        allowed = discord.AllowedMentions(users=True)

        if not top:
            await ctx.send(
                f"🔔 {user_mention}, a busca por **`{final_prod}`** "
                f"(📂 **{rule.label}**) terminou, mas nenhuma oferta relevante foi encontrada.",
                allowed_mentions=allowed,
            )
            return

        raw_embeds = build_discord_embeds(final_prod, top, results, used_fallback)
        discord_embeds = [discord.Embed.from_dict(e) for e in raw_embeds]
        await ctx.send(
            content=(
                f"🔔 {user_mention}, sua pesquisa ficou pronta!\n"
                f"🔎 **Top {len(top)} ofertas mais baratas e confiáveis para:** `{final_prod}` "
                f"*(📂 {rule.label})*"
            ),
            embeds=discord_embeds,
            allowed_mentions=allowed,
        )

    return bot


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    token = get_bot_token()
    try:
        bot = create_bot(enable_message_content=True)
        await bot.start(token)
    except discord.errors.PrivilegedIntentsRequired:
        print(
            "[!] 'Message Content Intent' não está ativo no portal do Discord; "
            "iniciando com Slash Command (/preco) ativo!"
        )
        bot = create_bot(enable_message_content=False)
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
