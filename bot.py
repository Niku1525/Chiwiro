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

intents = discord.Intents.default()
intents.message_content = False
intents.voice_states = True

bot = commands.Bot(intents=intents)


@bot.event
async def on_ready():
    log.info(f"Conectado como {bot.user} (id={bot.user.id})")
    log.info("Servidores: " + ", ".join(g.name for g in bot.guilds))


def main():
    if not TOKEN:
        raise RuntimeError(
            "No se encontró DISCORD_TOKEN. Copia .env.example a .env y pon tu token ahí."
        )

    bot.load_extension("cogs.music")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
