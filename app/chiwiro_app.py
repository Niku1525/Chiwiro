# -*- coding: utf-8 -*-
"""Ventana de control de Chiwiro Music ♡ tema Cinnamoroll.

Arranca bot.py como un proceso aparte y muestra su estado y su log en vivo.
Se abre con pythonw.exe, así que no aparece ninguna consola negra.

Para ejecutarlo a mano:  venv\\Scripts\\pythonw.exe chiwiro_app.py
"""
import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

import psutil
from PIL import Image, ImageTk

# La app vive en app/, así que la raíz del proyecto es la carpeta de
# arriba: de ahí cuelgan bot.py, el venv, el .env y los iconos.
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(BASE, "venv", "Scripts", "python.exe")
BOT = os.path.join(BASE, "bot.py")
ICONO = os.path.join(BASE, "assets", "chiwiro.ico")
ICONO_GRANDE = os.path.join(BASE, "assets", "cinnamoroll-100.ico")
ENV = os.path.join(BASE, ".env")
CONFIG = os.path.join(BASE, "data", "app_config.json")

# Tiene que ser idéntico al del acceso directo (ver
# tools/create_shortcut.py) o Windows abre dos botones en la
# barra de tareas: uno del icono anclado y otro de la ventana.
APP_ID = "Chiwiro.Music.Bot"

MAX_LINEAS_LOG = 600

# --------------------------------------------------------------- paletas
# El malva #8d6c9f y el crema #f9eede salen del propio icono.
TEMAS = {
    "claro": {
        "fondo": "#fdf1f6",
        "panel": "#ffffff",
        "nube": "#fbe4ef",
        "deco": "#f9d6e6",
        "titulo": "#8d6c9f",
        "texto": "#7c5f70",
        "tenue": "#bda2b2",
        "scroll_riel": "#f6e8f0",
        "principal": "#e58bb0",
        "principal_hover": "#ef9fc2",
        "principal_texto": "#ffffff",
        "detener": "#f0a3c4",
        "detener_hover": "#f6b8d3",
        "detener_texto": "#7a3352",
        "crema": "#f9eede",
        "crema_hover": "#f3e3cd",
        "crema_texto": "#96733f",
        "lila": "#f2e9f7",
        "lila_hover": "#e6d6f0",
        "lila_texto": "#8d6c9f",
        "rosa": "#fde9f1",
        "rosa_hover": "#f9cede",
        "rosa_texto": "#c4718f",
        "ok": "#4f9b7a",
        "ok_fondo": "#e6f6ee",
        "aviso": "#b98533",
        "aviso_fondo": "#fbf1e3",
        "error": "#c96f6f",
        "error_fondo": "#fdeeee",
        "dormido_fondo": "#f6e8f0",
    },
    "oscuro": {
        "fondo": "#221a28",
        "panel": "#2d2234",
        "nube": "#372940",
        "deco": "#3f2f4a",
        "titulo": "#f0b8d4",
        "texto": "#e9d9e4",
        "tenue": "#a288ab",
        "scroll_riel": "#372940",
        "principal": "#e58bb0",
        "principal_hover": "#f0a3c4",
        "principal_texto": "#2b1f31",
        "detener": "#4d3247",
        "detener_hover": "#5d3d57",
        "detener_texto": "#f6b8d3",
        "crema": "#3d3020",
        "crema_hover": "#4b3b28",
        "crema_texto": "#f0d9b8",
        "lila": "#382a42",
        "lila_hover": "#453352",
        "lila_texto": "#d9b8ec",
        "rosa": "#3d2839",
        "rosa_hover": "#4d3247",
        "rosa_texto": "#f0a3c4",
        "ok": "#8fd9b6",
        "ok_fondo": "#26382f",
        "aviso": "#e8c07d",
        "aviso_fondo": "#3a3125",
        "error": "#f0a0a0",
        "error_fondo": "#3d2a2a",
        "dormido_fondo": "#372940",
    },
}


def token_configurado() -> bool:
    """True si el .env tiene un DISCORD_TOKEN con algo adentro."""
    try:
        with open(ENV, encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if linea.startswith("DISCORD_TOKEN=") and linea.split("=", 1)[1].strip():
                    return True
    except OSError:
        pass
    return False


def leer_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def guardar_config(datos: dict):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2)
    except OSError:
        pass


def bots_huerfanos() -> list:
    """Busca instancias de bot.py de ESTA carpeta que hayan quedado dando
    vueltas: si la app se cierra de golpe (o se mata desde el Administrador
    de tareas), el proceso hijo sobrevive y se queda conectado a Discord.
    Con dos vivos el bot contesta dos veces a cada comando."""
    encontrados = []
    for proceso in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proceso.info["pid"] == os.getpid():
                continue
            if not (proceso.info["name"] or "").lower().startswith("python"):
                continue
            argumentos = proceso.info["cmdline"] or []
            if any(a.replace("/", "\\").endswith(BOT.replace("/", "\\"))
                   or a == BOT for a in argumentos):
                encontrados.append(proceso)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return encontrados


def redondeado(canvas, x0, y0, x1, y1, radio, **kwargs):
    """Rectángulo de esquinas redondeadas, como polígono suavizado."""
    puntos = [
        x0 + radio, y0, x1 - radio, y0, x1, y0, x1, y0 + radio,
        x1, y1 - radio, x1, y1, x1 - radio, y1, x0 + radio, y1,
        x0, y1, x0, y1 - radio, x0, y0 + radio, x0, y0,
    ]
    return canvas.create_polygon(puntos, smooth=True, **kwargs)


class BotonBonito(tk.Canvas):
    """Botón redondeado con hover. El tk.Button nativo es un rectángulo
    gris con borde que rompe cualquier tema."""

    def __init__(self, padre, texto, comando, fondo, texto_color, fondo_pagina,
                 fondo_hover=None, ancho=None, fuente=None, **kw):
        self.fuente = fuente or tkfont.Font(family="Segoe UI", size=10, weight="bold")
        ancho = ancho or self.fuente.measure(texto) + 36
        super().__init__(padre, width=ancho, height=38, bg=fondo_pagina,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self.comando = comando
        self.fondo = fondo
        self.fondo_hover = fondo_hover or fondo
        self.habilitado = True

        self.forma = redondeado(self, 1, 1, ancho - 1, 37, 15, fill=fondo, outline="")
        self.etiqueta = self.create_text(ancho / 2, 19, text=texto,
                                         fill=texto_color, font=self.fuente)

        self.bind("<Enter>", lambda _: self.itemconfigure(self.forma, fill=self.fondo_hover))
        self.bind("<Leave>", lambda _: self.itemconfigure(self.forma, fill=self.fondo))
        self.bind("<Button-1>", lambda _: self.comando and self.comando())

    def configurar(self, texto=None, fondo=None, texto_color=None, fondo_hover=None):
        if texto is not None:
            self.itemconfigure(self.etiqueta, text=texto)
        if fondo is not None:
            self.fondo = fondo
            self.itemconfigure(self.forma, fill=fondo)
        if fondo_hover is not None:
            self.fondo_hover = fondo_hover
        if texto_color is not None:
            self.itemconfigure(self.etiqueta, fill=texto_color)


class ChiwiroApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proceso = None
        self.cola = queue.Queue()
        self.entradas = []          # (hora, texto, etiqueta) para poder repintar

        self.config = leer_config()
        self.tema = self.config.get("tema", "claro")

        self._estado_texto = "durmiendo~"
        self._estado_clave = "dormido"
        self._estado_detalle = ""

        root.title("Chiwiro")
        root.geometry("660x520")
        root.minsize(560, 430)
        root.protocol("WM_DELETE_WINDOW", self.al_cerrar)

        self._cargar_fuentes()
        self._cargar_icono()
        self._construir_interfaz()
        self._revisar_cola()

        # "Abrirla y que se ejecute todo": arranca sola al abrir la ventana.
        root.after(400, self.iniciar)

    @property
    def c(self) -> dict:
        return TEMAS[self.tema]

    # --------------------------------------------------------------- icono

    def _cargar_icono(self):
        if os.path.exists(ICONO):
            try:
                self.root.iconbitmap(default=ICONO)
            except tk.TclError:
                pass
        self.root.after(60, self._icono_nitido)

        try:
            imagen = Image.open(ICONO_GRANDE).convert("RGBA").resize((76, 76), Image.LANCZOS)
            self.icono_tk = ImageTk.PhotoImage(imagen)
        except Exception:
            self.icono_tk = None

    def _icono_nitido(self):
        """Tk elige una sola imagen del .ico y la reescala él mismo, lo que
        deja el icono de la barra de título borroso. Cargamos a mano el
        tamaño exacto que Windows va a mostrar (16 chico, 32 grande) y se lo
        mandamos a la ventana con WM_SETICON."""
        try:
            import ctypes
            usuario = ctypes.windll.user32
            try:
                hwnd = int(self.root.wm_frame(), 16)
            except (ValueError, tk.TclError):
                hwnd = self.root.winfo_id()

            IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x0010, 0x0080
            for tam, cual in ((16, 0), (32, 1)):      # 0 = ICON_SMALL, 1 = ICON_BIG
                manejador = usuario.LoadImageW(None, ICONO, IMAGE_ICON, tam, tam,
                                               LR_LOADFROMFILE)
                if manejador:
                    usuario.SendMessageW(hwnd, WM_SETICON, cual, manejador)
        except Exception:
            pass

    # ------------------------------------------------------------------ UI

    def _cargar_fuentes(self):
        familias = set(tkfont.families())

        def elegir(*opciones):
            for o in opciones:
                if o in familias:
                    return o
            return "Segoe UI"

        titulo = elegir("Ink Free", "Comic Sans MS", "Segoe UI")
        cuerpo = elegir("Segoe UI", "Candara")

        self.f_titulo = tkfont.Font(family=titulo, size=23)
        self.f_sub = tkfont.Font(family=cuerpo, size=9)
        self.f_estado = tkfont.Font(family=cuerpo, size=10, weight="bold")
        self.f_boton = tkfont.Font(family=cuerpo, size=10, weight="bold")
        self.f_log = tkfont.Font(family=cuerpo, size=9)
        self.f_hora = tkfont.Font(family=elegir("Consolas", "Courier New"), size=8)

    def _construir_interfaz(self):
        c = self.c
        self.root.configure(bg=c["fondo"])

        # ---------------------------------------------------- encabezado
        self.cabecera = tk.Canvas(self.root, bg=c["fondo"], height=124,
                                  highlightthickness=0, bd=0)
        self.cabecera.pack(fill="x")
        self.cabecera.bind("<Configure>", self._dibujar_cabecera)

        # ------------------------------------------------------- botones
        self.barra_botones = tk.Frame(self.root, bg=c["fondo"])
        self.barra_botones.pack(fill="x", padx=22, pady=(2, 12))
        b = self.barra_botones

        self.boton_encendido = BotonBonito(
            b, "♡   Iniciar", self.alternar, c["principal"], c["principal_texto"],
            c["fondo"], fondo_hover=c["principal_hover"], ancho=142, fuente=self.f_boton)
        self.boton_encendido.pack(side="left")

        BotonBonito(b, "Configurar", self.abrir_env, c["crema"], c["crema_texto"],
                    c["fondo"], fondo_hover=c["crema_hover"],
                    fuente=self.f_boton).pack(side="left", padx=(10, 0))
        BotonBonito(b, "Copiar log", self.copiar_log, c["lila"], c["lila_texto"],
                    c["fondo"], fondo_hover=c["lila_hover"],
                    fuente=self.f_boton).pack(side="left", padx=(10, 0))

        BotonBonito(b, "Ocultar", self.root.iconify, c["rosa"], c["rosa_texto"],
                    c["fondo"], fondo_hover=c["rosa_hover"],
                    fuente=self.f_boton).pack(side="right")
        etiqueta_tema = "☾  Oscuro" if self.tema == "claro" else "☀  Claro"
        BotonBonito(b, etiqueta_tema, self.cambiar_tema, c["lila"], c["lila_texto"],
                    c["fondo"], fondo_hover=c["lila_hover"], ancho=104,
                    fuente=self.f_boton).pack(side="right", padx=(0, 10))

        # ----------------------------------------------------------- log
        self.envoltorio = tk.Frame(self.root, bg=c["fondo"])
        self.envoltorio.pack(fill="both", expand=True, padx=22, pady=(0, 20))

        self.fondo_log = tk.Canvas(self.envoltorio, bg=c["fondo"],
                                   highlightthickness=0, bd=0)
        self.fondo_log.pack(fill="both", expand=True)
        self.fondo_log.bind("<Configure>", self._dibujar_fondo_log)

        contenido = tk.Frame(self.fondo_log, bg=c["panel"])
        self.log = tk.Text(
            contenido, bg=c["panel"], fg=c["texto"], font=self.f_log, wrap="word",
            relief="flat", padx=6, pady=4, insertbackground=c["texto"],
            state="disabled", borderwidth=0, highlightthickness=0,
            spacing1=2, spacing3=2, cursor="arrow",
        )
        self.barra = tk.Scrollbar(contenido, command=self.log.yview,
                                  bg=c["panel"], troughcolor=c["scroll_riel"],
                                  activebackground=c["principal"], relief="flat",
                                  borderwidth=0, width=10)
        self.log.configure(yscrollcommand=self._ajustar_barra)
        self.barra.pack(side="right", fill="y", pady=6)
        self.log.pack(side="left", fill="both", expand=True)
        self.ventana_log = self.fondo_log.create_window(0, 0, window=contenido, anchor="nw")

        self.log.tag_configure("hora", foreground=c["tenue"], font=self.f_hora)
        self.log.tag_configure("normal", foreground=c["texto"])
        self.log.tag_configure("ok", foreground=c["ok"])
        self.log.tag_configure("aviso", foreground=c["aviso"])
        self.log.tag_configure("error", foreground=c["error"])

        self._repintar_log()

    # ------------------------------------------------------------- dibujo

    def _corazon(self, canvas, x, y, tam, color):
        """Un ♡ dibujado como texto: la fuente lo hace mejor que cualquier
        polígono que arme a mano."""
        canvas.create_text(x, y, text="♡", fill=color,
                           font=tkfont.Font(family="Segoe UI Symbol", size=tam))

    def _nube(self, canvas, cx, cy, escala, color):
        for dx, dy, r in [(-16, 4, 13), (0, -2, 18), (17, 5, 12), (0, 10, 15)]:
            canvas.create_oval(cx + (dx - r) * escala, cy + (dy - r) * escala,
                               cx + (dx + r) * escala, cy + (dy + r) * escala,
                               fill=color, outline="")

    def _dibujar_cabecera(self, evento=None):
        c = self.c
        lienzo = self.cabecera
        ancho = evento.width if evento else lienzo.winfo_width()
        lienzo.delete("all")

        # Nubecitas y corazones sueltos de fondo
        for cx, cy, escala in [(ancho - 78, 24, 1.1), (ancho - 152, 66, 0.75),
                               (ancho - 214, 20, 0.55)]:
            self._nube(lienzo, cx, cy, escala, c["nube"])
        for x, y, tam in [(ancho - 250, 62, 13), (ancho - 118, 100, 10),
                          (ancho - 46, 104, 15), (14, 30, 11), (10, 96, 14)]:
            self._corazon(lienzo, x, y, tam, c["deco"])

        redondeado(lienzo, 22, 10, max(ancho - 22, 220), 108, 26,
                   fill=c["panel"], outline="")

        if self.icono_tk is not None:
            lienzo.create_image(46, 59, image=self.icono_tk, anchor="w")

        lienzo.create_text(134, 44, text="Chiwiro", anchor="w",
                           fill=c["titulo"], font=self.f_titulo)
        lienzo.create_text(136, 74, text="♡  Tu bot de música en Discord  ♡",
                           anchor="w", fill=c["tenue"], font=self.f_sub)

        self._dibujar_pastilla(ancho)

    def _dibujar_pastilla(self, ancho=None):
        c = self.c
        lienzo = self.cabecera
        ancho = ancho or lienzo.winfo_width()
        lienzo.delete("pastilla")

        colores = {
            "dormido": (c["tenue"], c["dormido_fondo"]),
            "despertando": (c["aviso"], c["aviso_fondo"]),
            "linea": (c["ok"], c["ok_fondo"]),
            "error": (c["error"], c["error_fondo"]),
        }
        color, fondo = colores.get(self._estado_clave, colores["dormido"])

        x1 = ancho - 42
        x0 = x1 - self.f_estado.measure(self._estado_texto) - 46
        redondeado(lienzo, x0, 32, x1, 62, 15, fill=fondo, outline="", tags="pastilla")
        lienzo.create_oval(x0 + 16, 43, x0 + 26, 53, fill=color, outline="",
                           tags="pastilla")
        lienzo.create_text(x0 + 33, 47, text=self._estado_texto, anchor="w",
                           fill=color, font=self.f_estado, tags="pastilla")
        if self._estado_detalle:
            lienzo.create_text(x1, 80, text=self._estado_detalle[:44], anchor="e",
                               fill=c["tenue"], font=self.f_sub, tags="pastilla")

    def _dibujar_fondo_log(self, evento=None):
        lienzo = self.fondo_log
        ancho = evento.width if evento else lienzo.winfo_width()
        alto = evento.height if evento else lienzo.winfo_height()
        lienzo.delete("fondo")
        redondeado(lienzo, 0, 0, ancho, alto, 24, fill=self.c["panel"],
                   outline="", tags="fondo")
        lienzo.tag_lower("fondo")
        lienzo.coords(self.ventana_log, 16, 18)
        lienzo.itemconfigure(self.ventana_log, width=max(ancho - 32, 50),
                             height=max(alto - 34, 50))

    def _ajustar_barra(self, primero, ultimo):
        """Esconde la barra de scroll mientras no haya nada que scrollear:
        la barra nativa de Windows es gris y se pelea con el tema."""
        if float(primero) <= 0.0 and float(ultimo) >= 1.0:
            self.barra.pack_forget()
        elif not self.barra.winfo_ismapped():
            self.barra.pack(side="right", fill="y", pady=6, before=self.log)
        self.barra.set(primero, ultimo)

    # --------------------------------------------------------------- tema

    def cambiar_tema(self):
        self.tema = "oscuro" if self.tema == "claro" else "claro"
        self.config["tema"] = self.tema
        guardar_config(self.config)

        for hijo in self.root.winfo_children():
            hijo.destroy()
        self._construir_interfaz()
        self.root.update_idletasks()
        self._dibujar_cabecera()
        self._dibujar_fondo_log()

        if self.corriendo:
            self.boton_encendido.configurar(
                texto="■   Detener", fondo=self.c["detener"],
                fondo_hover=self.c["detener_hover"], texto_color=self.c["detener_texto"])

    # ---------------------------------------------------------------- log

    ADORNOS = {"ok": "♡ ", "aviso": "✿ ", "error": "✖ ", "normal": ""}

    def escribir(self, texto, etiqueta="normal"):
        self.entradas.append((time.strftime("%H:%M"), texto.rstrip(), etiqueta))
        if len(self.entradas) > MAX_LINEAS_LOG:
            self.entradas = self.entradas[-MAX_LINEAS_LOG:]
            self._repintar_log()
            return
        self._pintar_entrada(self.entradas[-1])
        self.log.see("end")

    def _pintar_entrada(self, entrada):
        hora, texto, etiqueta = entrada
        self.log.configure(state="normal")
        self.log.insert("end", hora + "  ", "hora")
        self.log.insert("end", self.ADORNOS.get(etiqueta, "") + texto + "\n", etiqueta)
        self.log.configure(state="disabled")

    def _repintar_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        for entrada in self.entradas:
            self._pintar_entrada(entrada)
        self.log.see("end")

    def _poner_estado(self, texto, clave, detalle=None):
        self._estado_texto = texto
        self._estado_clave = clave
        if detalle is not None:
            self._estado_detalle = detalle
        self._dibujar_pastilla()

    # ------------------------------------------------------------ proceso

    @property
    def corriendo(self) -> bool:
        return self.proceso is not None and self.proceso.poll() is None

    def alternar(self):
        self.detener() if self.corriendo else self.iniciar()

    def iniciar(self):
        if self.corriendo:
            return

        if not os.path.exists(PYTHON):
            self.escribir("No encontré el entorno virtual (venv). Abre una terminal "
                          "en esta carpeta y ejecuta:  python -m venv venv", "error")
            self.escribir("Después:  venv\\Scripts\\pip install -r requirements.txt",
                          "error")
            return

        if not token_configurado():
            self._poner_estado("falta el token", "despertando")
            self.escribir("El archivo .env no tiene el token del bot.", "aviso")
            self.escribir('Haz clic en "Configurar", pega el token en DISCORD_TOKEN=, '
                          "guarda y vuelve a darle a Iniciar.", "aviso")
            self.escribir("El token se saca de discord.com/developers/applications "
                          "→ tu app → Bot → Reset Token.", "aviso")
            return

        # Antes de encender, barremos instancias viejas. Sin esto, dos
        # copias del bot contestan cada comando por duplicado.
        huerfanos = bots_huerfanos()
        if huerfanos:
            self.escribir(f"Había {len(huerfanos)} instancia(s) del bot dando "
                          f"vueltas de antes. Las cierro para que no conteste "
                          f"doble.", "aviso")
            for proceso in huerfanos:
                try:
                    proceso.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            psutil.wait_procs(huerfanos, timeout=5)

        entorno = dict(os.environ)
        # Sin esto, un título de canción con emoji revienta el log del bot.
        entorno["PYTHONIOENCODING"] = "utf-8"

        banderas = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            self.proceso = subprocess.Popen(
                [PYTHON, "-u", BOT], cwd=BASE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, env=entorno, creationflags=banderas,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as e:
            self.escribir(f"No pude arrancar el bot: {e}", "error")
            return

        threading.Thread(target=self._leer_salida, args=(self.proceso,),
                         daemon=True).start()

        self._poner_estado("despertando...", "despertando")
        self.boton_encendido.configurar(texto="■   Detener", fondo=self.c["detener"],
                                        fondo_hover=self.c["detener_hover"],
                                        texto_color=self.c["detener_texto"])
        self.escribir("Arrancando el bot...", "ok")

    def _leer_salida(self, proceso):
        for linea in proceso.stdout:
            self.cola.put(("log", linea))
        proceso.stdout.close()
        self.cola.put(("fin", proceso.wait()))

    def detener(self):
        if not self.corriendo:
            return
        self.escribir("Deteniendo el bot...", "aviso")
        try:
            # Ctrl+Break le llega como KeyboardInterrupt, así que se despide
            # de Discord como corresponde en vez de morir de golpe.
            self.proceso.send_signal(signal.CTRL_BREAK_EVENT)
            self.proceso.wait(timeout=6)
        except Exception:
            try:
                self.proceso.terminate()
                self.proceso.wait(timeout=4)
            except Exception:
                self.proceso.kill()

    # ------------------------------------------------------------ eventos

    def _revisar_cola(self):
        try:
            while True:
                tipo, dato = self.cola.get_nowait()
                if tipo == "log":
                    self._procesar_linea(dato)
                else:
                    self._proceso_termino(dato)
        except queue.Empty:
            pass
        self.root.after(120, self._revisar_cola)

    @staticmethod
    def _es_ruido(linea: str) -> bool:
        """discord.py loguea en INFO el payload entero del gateway (un JSON
        gigante con métricas internas). No aporta nada y tapa el resto, así
        que escondemos lo que sea INFO de los loggers de discord.*. Los
        avisos y errores de esos mismos loggers sí se muestran."""
        if "[INFO]" not in linea:
            return False
        resto = linea.split("[INFO]", 1)[1].strip()
        return resto.split(":", 1)[0].strip().startswith("discord.")

    def _procesar_linea(self, linea):
        limpia = linea.rstrip()
        if not limpia or self._es_ruido(limpia):
            return

        etiqueta = "normal"
        if "[ERROR]" in limpia or "Traceback" in limpia:
            etiqueta = "error"
        elif "[WARNING]" in limpia:
            etiqueta = "aviso"

        if "Conectado como" in limpia:
            nombre = limpia.split("Conectado como", 1)[1].split("(id=")[0].strip()
            self._poner_estado("en línea ♡", "linea", nombre)
            etiqueta = "ok"
        elif "Servidores:" in limpia:
            self._estado_detalle = limpia.split("Servidores:", 1)[1].strip()
            self._dibujar_pastilla()
        elif "No se encontró DISCORD_TOKEN" in limpia:
            self._poner_estado("falta el token", "despertando")
            etiqueta = "error"

        # Le sacamos el prefijo del logging (fecha, nivel y nombre del
        # logger), que en una ventana propia sobra.
        for marca in ("[INFO] ", "[WARNING] ", "[ERROR] "):
            if marca in limpia:
                limpia = limpia.split(marca, 1)[1]
                nombre, sep, mensaje = limpia.partition(": ")
                if sep and " " not in nombre:
                    limpia = mensaje
                break

        self.escribir(limpia, etiqueta)

    def _proceso_termino(self, codigo):
        self.proceso = None
        self.boton_encendido.configurar(texto="♡   Iniciar", fondo=self.c["principal"],
                                        fondo_hover=self.c["principal_hover"],
                                        texto_color=self.c["principal_texto"])
        if codigo == 0:
            self._poner_estado("durmiendo~", "dormido", "")
            self.escribir("El bot se detuvo. ¡Hasta la próxima!", "aviso")
        else:
            self._poner_estado("se cayó :(", "error", "")
            self.escribir(f"El bot se cerró con código {codigo}. Mira el log de "
                          f"arriba para ver qué pasó.", "error")

    def abrir_env(self):
        if not os.path.exists(ENV):
            ejemplo = os.path.join(BASE, ".env.example")
            if os.path.exists(ejemplo):
                with open(ejemplo, encoding="utf-8") as origen, \
                     open(ENV, "w", encoding="utf-8") as destino:
                    destino.write(origen.read())
                self.escribir("Creé un .env nuevo a partir de .env.example.", "aviso")
        try:
            os.startfile(ENV)
        except OSError:
            subprocess.Popen(["notepad.exe", ENV])

    def copiar_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(
            f"{h}  {t}" for h, t, _ in self.entradas))
        self.escribir("Log copiado al portapapeles.", "ok")

    def al_cerrar(self):
        if self.corriendo:
            self.detener()
        self.root.destroy()


def main():
    # Para que Windows agrupe la ventana con el acceso directo anclado.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    root = tk.Tk()
    ChiwiroApp(root)

    # Con --minimizado la ventana arranca guardada en la barra de tareas.
    # Lo usa el acceso directo de inicio automático: el bot se enciende
    # igual, pero no te salta la ventana cada vez que prendes la PC.
    # (Tk no hace caso al "minimizado" del acceso directo, por eso el flag.)
    if "--minimizado" in sys.argv:
        root.after(120, root.iconify)

    root.mainloop()


if __name__ == "__main__":
    main()
