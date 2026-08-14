# Bot de música para Discord (YouTube / YouTube Music)

Bot armado con **py-cord** + **yt-dlp** + **FFmpeg**. Funciona con cualquier
link soportado por yt-dlp (YouTube, YouTube Music, y en general lo que
yt-dlp reconozca) — no está limitado a "canciones cortas": si le pasás un
video de 40 minutos o un documental, extrae y reproduce solo el audio igual.

## 1. Requisitos

- Python 3.10+
- FFmpeg instalado y accesible en el PATH
- Una app/bot creado en el [Discord Developer Portal](https://discord.com/developers/applications)

### Instalar FFmpeg

**Windows:** descargar desde https://www.gyan.dev/ffmpeg/builds/ y agregar la
carpeta `bin` al PATH.

**Linux (Debian/Ubuntu):**
```bash
sudo apt update && sudo apt install ffmpeg
```

**Arch:**
```bash
sudo pacman -S ffmpeg
```

## 2. Instalación del bot

```bash
cd discord-music-bot
python -m venv venv
source venv/bin/activate   # en Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Copiá `.env.example` a `.env` y poné tu token:
```bash
cp .env.example .env
```
```
DISCORD_TOKEN=el_token_de_tu_bot
```

## 3. Configurar el bot en Discord Developer Portal

1. Andá a https://discord.com/developers/applications → tu app.
2. **Bot** → copiá el token y pegalo en `.env`.
3. En **Bot**, activá el intent **Server Members** no es necesario, pero
   dejá **Message Content Intent** desactivado (no lo usamos, todo es por
   slash commands).
4. En **OAuth2 → URL Generator**, marcá el scope `bot` y `applications.commands`,
   y en permisos marcá: `Connect`, `Speak`, `Send Messages`, `Use Slash Commands`.
5. Usá la URL generada para invitar el bot a tu servidor.

## 4. Correr el bot

```bash
python bot.py
```

Los slash commands (`/play`, `/skip`, etc.) pueden tardar hasta una hora en
aparecer globalmente la primera vez; si querés que aparezcan al instante en
tu servidor de pruebas, decime el `guild_id` y te dejo el código ajustado
para registrar los comandos solo en ese servidor (aparecen al instante).

## 5. Comandos disponibles

| Comando            | Descripción                                      |
|---------------------|--------------------------------------------------|
| `/play <link o texto>` | Reproduce o encola un link de YouTube/YT Music, o busca por texto |
| `/skip`             | Salta la canción actual                          |
| `/pause`            | Pausa                                             |
| `/resume`           | Reanuda                                           |
| `/stop`             | Detiene todo y vacía la cola                     |
| `/leave`            | Saca al bot del canal de voz                     |
| `/queue`            | Muestra qué está sonando y qué sigue             |
| `/volume <0-100>`   | Ajusta el volumen                                |

## Notas técnicas

- Cada servidor (`guild`) tiene su propio estado y su propia cola
  (`GuildMusicState`), así que el bot puede reproducir cosas distintas en
  distintos servidores al mismo tiempo.
- La extracción con yt-dlp corre en un thread aparte (`run_in_executor`)
  para no bloquear el event loop del bot mientras resuelve el link.
- `format: bestaudio/best` es lo que garantiza que solo se descargue/stream
  el audio, sin importar la duración del video — sirve igual para música
  de 3 minutos que para un documental de 2 horas.
- Si algún video da error por restricción de edad o región, se puede pasar
  cookies de tu navegador a yt-dlp (`cookiesfrombrowser`) — avisame si te
  pasa y lo agregamos.
- Playlists: ahora mismo `noplaylist=True` para simplificar. Si querés que
  al pasar un link de playlist se encole completa, es un cambio chico, avisame.
