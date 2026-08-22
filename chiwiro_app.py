# -*- coding: utf-8 -*-
"""Ventana de control de Chiwiro Music ✿ tema Cinnamoroll.

Arranca bot.py como un proceso aparte y muestra su estado y su log en vivo.
Se abre con pythonw.exe, así que no aparece ninguna consola negra.

Para ejecutarlo a mano:  venv\\Scripts\\pythonw.exe chiwiro_app.py
"""
import os
import queue
import signal
import subprocess
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

from PIL import Image, ImageTk

BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(BASE, "venv", "Scripts", "python.exe")
BOT = os.path.join(BASE, "bot.py")
ICONO = os.path.join(BASE, "chiwiro.ico")
ICONO_GRANDE = os.path.join(BASE, "icons8-rollo-de-canela-100.ico")
ENV = os.path.join(BASE, ".env")

MAX_LINEAS_LOG = 600

# ---------------------------------------------------------------- paleta
# Sacada del propio icono (malva y crema) y del celeste de Cinnamoroll.
CIELO = "#eef4fc"        # fondo general, celeste muy suave
NUBE = "#ffffff"         # paneles
MALVA = "#8d6c9f"        # el trazo del icono
MALVA_CLARO = "#b79ac7"
MALVA_SUAVE = "#f0e9f5"
CREMA = "#f9eede"        # el relleno del icono
ROSA = "#f6bbd0"
ROSA_SUAVE = "#fdeef4"
CELESTE = "#a9cff0"
CELESTE_SUAVE = "#e6f1fb"
TEXTO = "#6b5b7b"
TENUE = "#a99bb5"
MENTA = "#7fc4a3"
MENTA_SUAVE = "#e6f6ee"
CORAL = "#e89b9b"
CORAL_SUAVE = "#fdeeee"
MIEL = "#e0b57c"
MIEL_SUAVE = "#fbf1e3"


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


def redondeado(canvas, x0, y0, x1, y1, radio, **kwargs):
    """Dibuja un rectángulo de esquinas redondeadas como polígono suavizado."""
    puntos = [
        x0 + radio, y0, x1 - radio, y0, x1, y0, x1, y0 + radio,
        x1, y1 - radio, x1, y1, x1 - radio, y1, x0 + radio, y1,
        x0, y1, x0, y1 - radio, x0, y0 + radio, x0, y0,
    ]
    return canvas.create_polygon(puntos, smooth=True, **kwargs)


class BotonBonito(tk.Canvas):
    """Botón redondeado con estados de hover, porque el tk.Button normal es
    un rectángulo gris que rompe todo el tema."""

    def __init__(self, padre, texto, comando, fondo, texto_color,
                 fondo_hover=None, ancho=None, fuente=None, **kw):
        self.fuente = fuente or tkfont.Font(family="Segoe UI", size=10, weight="bold")
        ancho = ancho or self.fuente.measure(texto) + 38
        super().__init__(padre, width=ancho, height=38, bg=CIELO,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self.comando = comando
        self.fondo = fondo
        self.fondo_hover = fondo_hover or fondo
        self.texto_color = texto_color
        self.habilitado = True

        self.forma = redondeado(self, 1, 1, ancho - 1, 37, 15, fill=fondo, outline="")
        self.etiqueta = self.create_text(ancho / 2, 19, text=texto,
                                         fill=texto_color, font=self.fuente)

        self.bind("<Enter>", self._entrar)
        self.bind("<Leave>", self._salir)
        self.bind("<Button-1>", self._click)

    def _entrar(self, _=None):
        if self.habilitado:
            self.itemconfigure(self.forma, fill=self.fondo_hover)

    def _salir(self, _=None):
        if self.habilitado:
            self.itemconfigure(self.forma, fill=self.fondo)

    def _click(self, _=None):
        if self.habilitado and self.comando:
            self.comando()

    def configurar(self, texto=None, fondo=None, texto_color=None, fondo_hover=None):
        if texto is not None:
            self.itemconfigure(self.etiqueta, text=texto)
        if fondo is not None:
            self.fondo = fondo
            self.itemconfigure(self.forma, fill=fondo)
        if fondo_hover is not None:
            self.fondo_hover = fondo_hover
        if texto_color is not None:
            self.texto_color = texto_color
            self.itemconfigure(self.etiqueta, fill=texto_color)


class ChiwiroApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proceso = None
        self.cola = queue.Queue()
        self.lineas = 0

        root.title("Chiwiro Music")
        root.configure(bg=CIELO)
        root.geometry("660x520")
        root.minsize(560, 420)
        if os.path.exists(ICONO):
            try:
                root.iconbitmap(default=ICONO)
            except tk.TclError:
                pass
        root.protocol("WM_DELETE_WINDOW", self.al_cerrar)

        self._estado_texto = "durmiendo~"
        self._estado_color = TENUE
        self._estado_fondo = MALVA_SUAVE
        self._estado_detalle = ""

        self._cargar_fuentes()
        self._construir_interfaz()
        self._revisar_cola()

        # "Abrirla y que se ejecute todo": arranca sola al abrir la ventana.
        root.after(400, self.iniciar)

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

        self.f_titulo = tkfont.Font(family=titulo, size=22)
        self.f_sub = tkfont.Font(family=cuerpo, size=9)
        self.f_estado = tkfont.Font(family=cuerpo, size=10, weight="bold")
        self.f_boton = tkfont.Font(family=cuerpo, size=10, weight="bold")
        self.f_log = tkfont.Font(family=cuerpo, size=9)
        self.f_hora = tkfont.Font(family=elegir("Consolas", "Courier New"), size=8)

    def _construir_interfaz(self):
        # ---------------------------------------------------- encabezado
        self.cabecera = tk.Canvas(self.root, bg=CIELO, height=118,
                                  highlightthickness=0, bd=0)
        self.cabecera.pack(fill="x")
        self.cabecera.bind("<Configure>", self._dibujar_cabecera)

        try:
            imagen = Image.open(ICONO_GRANDE).convert("RGBA").resize((72, 72), Image.LANCZOS)
            self.icono_tk = ImageTk.PhotoImage(imagen)
        except Exception:
            self.icono_tk = None

        # ------------------------------------------------------- botones
        botones = tk.Frame(self.root, bg=CIELO)
        botones.pack(fill="x", padx=22, pady=(2, 12))

        # Solo usamos glifos que Segoe UI dibuja bien (♪ ■ ♡). El resto va
        # con palabras: un glifo que el sistema no tiene se ve como cuadrito
        # y arruina más de lo que decora.
        self.boton_encendido = BotonBonito(
            botones, "♪   Iniciar", self.alternar, MALVA, "#ffffff",
            fondo_hover=MALVA_CLARO, ancho=140, fuente=self.f_boton)
        self.boton_encendido.pack(side="left")

        BotonBonito(botones, "Configurar", self.abrir_env, CREMA, MALVA,
                    fondo_hover="#f3e3cd", fuente=self.f_boton).pack(side="left", padx=(10, 0))
        BotonBonito(botones, "Copiar log", self.copiar_log, CELESTE_SUAVE, "#5b87ad",
                    fondo_hover=CELESTE, fuente=self.f_boton).pack(side="left", padx=(10, 0))
        BotonBonito(botones, "Ocultar", self.root.iconify, ROSA_SUAVE, "#c4718f",
                    fondo_hover=ROSA, fuente=self.f_boton).pack(side="right")

        # ----------------------------------------------------------- log
        envoltorio = tk.Frame(self.root, bg=CIELO)
        envoltorio.pack(fill="both", expand=True, padx=22, pady=(0, 20))

        self.fondo_log = tk.Canvas(envoltorio, bg=CIELO, highlightthickness=0, bd=0)
        self.fondo_log.pack(fill="both", expand=True)
        self.fondo_log.bind("<Configure>", self._dibujar_fondo_log)

        contenido = tk.Frame(self.fondo_log, bg=NUBE)
        self.log = tk.Text(
            contenido, bg=NUBE, fg=TEXTO, font=self.f_log, wrap="word",
            relief="flat", padx=6, pady=4, insertbackground=TEXTO,
            state="disabled", borderwidth=0, highlightthickness=0,
            spacing1=2, spacing3=2, cursor="arrow",
        )
        self.barra = tk.Scrollbar(contenido, command=self.log.yview,
                                  bg=NUBE, troughcolor=MALVA_SUAVE,
                                  activebackground=MALVA_CLARO, relief="flat",
                                  borderwidth=0, width=10)
        self.log.configure(yscrollcommand=self._ajustar_barra)
        self.barra.pack(side="right", fill="y", pady=6)
        self.log.pack(side="left", fill="both", expand=True)
        self.ventana_log = self.fondo_log.create_window(0, 0, window=contenido, anchor="nw")

        self.log.tag_configure("hora", foreground=TENUE, font=self.f_hora)
        self.log.tag_configure("normal", foreground=TEXTO)
        self.log.tag_configure("ok", foreground="#4f9b7a")
        self.log.tag_configure("aviso", foreground="#b98533")
        self.log.tag_configure("error", foreground="#c96f6f")

    def _dibujar_cabecera(self, evento=None):
        c = self.cabecera
        ancho = evento.width if evento else c.winfo_width()
        c.delete("all")

        # Nubecitas de fondo, para que no sea un rectángulo plano.
        for cx, cy, escala, color in [
            (ancho - 70, 26, 1.15, "#e2edfa"), (ancho - 140, 62, 0.8, "#e8f1fb"),
            (ancho - 200, 22, 0.6, "#eaf2fc"),
        ]:
            self._nube(c, cx, cy, escala, color)

        # Tarjeta blanca
        redondeado(c, 22, 10, max(ancho - 22, 200), 104, 24, fill=NUBE, outline="")

        if self.icono_tk is not None:
            c.create_image(44, 57, image=self.icono_tk, anchor="w")

        c.create_text(130, 42, text="Chiwiro Music", anchor="w",
                      fill=MALVA, font=self.f_titulo)
        c.create_text(132, 70, text="✿  tu bot de música en Discord", anchor="w",
                      fill=TENUE, font=self.f_sub)

        # Pastilla de estado
        self._dibujar_pastilla(ancho)

    def _nube(self, canvas, cx, cy, escala, color):
        for dx, dy, r in [(-16, 4, 13), (0, -2, 18), (17, 5, 12), (0, 10, 15)]:
            canvas.create_oval(
                cx + (dx - r) * escala, cy + (dy - r) * escala,
                cx + (dx + r) * escala, cy + (dy + r) * escala,
                fill=color, outline="")

    def _dibujar_pastilla(self, ancho=None):
        c = self.cabecera
        ancho = ancho or c.winfo_width()
        c.delete("pastilla")

        texto = getattr(self, "_estado_texto", "durmiendo~")
        color = getattr(self, "_estado_color", TENUE)
        fondo = getattr(self, "_estado_fondo", MALVA_SUAVE)
        detalle = getattr(self, "_estado_detalle", "")

        ancho_texto = self.f_estado.measure(texto)
        x1 = ancho - 40
        x0 = x1 - ancho_texto - 44
        redondeado(c, x0, 30, x1, 60, 15, fill=fondo, outline="", tags="pastilla")
        c.create_oval(x0 + 15, 41, x0 + 25, 51, fill=color, outline="", tags="pastilla")
        c.create_text(x0 + 32, 45, text=texto, anchor="w", fill=color,
                      font=self.f_estado, tags="pastilla")
        if detalle:
            c.create_text(x1, 74, text=detalle[:46], anchor="e", fill=TENUE,
                          font=self.f_sub, tags="pastilla")

    def _ajustar_barra(self, primero, ultimo):
        """Esconde la barra de scroll mientras no haya nada que scrollear:
        la barra nativa de Windows es gris y se pelea con el tema."""
        if float(primero) <= 0.0 and float(ultimo) >= 1.0:
            self.barra.pack_forget()
        elif not self.barra.winfo_ismapped():
            self.barra.pack(side="right", fill="y", pady=6, before=self.log)
        self.barra.set(primero, ultimo)

    def _dibujar_fondo_log(self, evento=None):
        c = self.fondo_log
        ancho = evento.width if evento else c.winfo_width()
        alto = evento.height if evento else c.winfo_height()
        c.delete("fondo")
        redondeado(c, 0, 0, ancho, alto, 22, fill=NUBE, outline="", tags="fondo")
        c.tag_lower("fondo")
        c.coords(self.ventana_log, 16, 18)
        c.itemconfigure(self.ventana_log, width=max(ancho - 32, 50),
                        height=max(alto - 34, 50))

    def escribir(self, texto, etiqueta="normal", adorno=None):
        adornos = {"ok": "♡ ", "aviso": "! ", "error": "✖ ", "normal": ""}
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M  "), "hora")
        self.log.insert("end", (adorno or adornos.get(etiqueta, "")) + texto.rstrip() + "\n",
                        etiqueta)
        self.lineas += 1
        if self.lineas > MAX_LINEAS_LOG:
            self.log.delete("1.0", f"{self.lineas - MAX_LINEAS_LOG + 1}.0")
            self.lineas = MAX_LINEAS_LOG
        self.log.configure(state="disabled")
        self.log.see("end")

    def _poner_estado(self, texto, color, fondo, detalle=""):
        self._estado_texto = texto
        self._estado_color = color
        self._estado_fondo = fondo
        self._estado_detalle = detalle
        self._dibujar_pastilla()

    # -------------------------------------------------------------- proceso

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
            self.escribir("Después:  venv\\Scripts\\pip install -r requirements.txt", "error")
            return

        if not token_configurado():
            self._poner_estado("falta el token", "#b98533", MIEL_SUAVE)
            self.escribir("El archivo .env no tiene el token del bot.", "aviso")
            self.escribir('Haz clic en "✎ Configurar", pega el token en DISCORD_TOKEN=, '
                          "guarda y vuelve a darle a Iniciar.", "aviso")
            self.escribir("El token se saca de discord.com/developers/applications "
                          "→ tu app → Bot → Reset Token.", "aviso")
            return

        entorno = dict(os.environ)
        # Sin esto, un título de canción con emoji revienta el log del bot.
        entorno["PYTHONIOENCODING"] = "utf-8"

        banderas = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            self.proceso = subprocess.Popen(
                [PYTHON, "-u", BOT],
                cwd=BASE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=entorno,
                creationflags=banderas,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as e:
            self.escribir(f"No pude arrancar el bot: {e}", "error")
            return

        threading.Thread(target=self._leer_salida, args=(self.proceso,), daemon=True).start()

        self._poner_estado("despertando...", "#b98533", MIEL_SUAVE)
        self.boton_encendido.configurar(texto="■   Detener", fondo=ROSA,
                                        fondo_hover="#f3a8c2", texto_color="#8a4a63")
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

    # ------------------------------------------------------------- eventos

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
            self._poner_estado("en línea ♡", "#4f9b7a", MENTA_SUAVE, nombre)
            etiqueta = "ok"
        elif "Servidores:" in limpia:
            self._estado_detalle = limpia.split("Servidores:", 1)[1].strip()
            self._dibujar_pastilla()
        elif "No se encontró DISCORD_TOKEN" in limpia:
            self._poner_estado("falta el token", "#b98533", MIEL_SUAVE)
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
        self.boton_encendido.configurar(texto="♪   Iniciar", fondo=MALVA,
                                        fondo_hover=MALVA_CLARO, texto_color="#ffffff")
        if codigo == 0:
            self._poner_estado("durmiendo~", TENUE, MALVA_SUAVE)
            self.escribir("El bot se detuvo. ¡Hasta la próxima!", "aviso")
        else:
            self._poner_estado("se cayó :(", "#c96f6f", CORAL_SUAVE)
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
        self.root.clipboard_append(self.log.get("1.0", "end").strip())
        self.escribir("Log copiado al portapapeles.", "ok")

    def al_cerrar(self):
        if self.corriendo:
            self.detener()
        self.root.destroy()


def main():
    # Para que Windows agrupe la ventana con el acceso directo anclado y le
    # ponga nuestro icono en la barra de tareas.
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Chiwiro.Music.Bot")
    except Exception:
        pass

    root = tk.Tk()
    ChiwiroApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
