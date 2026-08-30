import os
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bot")

TOKEN = os.getenv("DISCORD_TOKEN")

GUILD_IDS = [int(x) for x in os.getenv("DISCORD_GUILD_IDS", "").replace(" ", "").split(",") if x]

intents = discord.Intents.default()
intents.message_content = False
intents.voice_states = True

bot = commands.Bot(intents=intents, debug_guilds=GUILD_IDS or None)


@bot.event
async def on_ready():
    log.info(f"Conectado como {bot.user} (id={bot.user.id})")
    log.info("Servidores: " + ", ".join(g.name for g in bot.guilds))

    if GUILD_IDS:
        log.info(f"Comandos registrados en {len(GUILD_IDS)} servidor(es): aparecen al instante")
        try:
            globales = await bot.http.get_global_commands(bot.application_id)
            if globales:
                await bot.http.bulk_upsert_global_commands(bot.application_id, [])
                log.info(f"Quité {len(globales)} comandos globales para que no salgan duplicados")
        except Exception:
            log.exception("No pude limpiar los comandos globales")


def main():
    if not TOKEN:
        raise RuntimeError(
            "No se encontró DISCORD_TOKEN. Copia .env.example a .env y pon tu token ahí."
        )

    bot.load_extension("cogs.music")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
