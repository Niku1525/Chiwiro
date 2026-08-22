# -*- coding: utf-8 -*-
"""Ventana de control de Chiwiro Music.

Arranca bot.py como un proceso aparte y muestra su estado y su log en vivo.
Se abre con pythonw.exe, así que no aparece ninguna consola negra.

Para ejecutarlo a mano:  venv\\Scripts\\pythonw.exe chiwiro_app.py
"""
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import font as tkfont

BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = os.path.join(BASE, "venv", "Scripts", "python.exe")
BOT = os.path.join(BASE, "bot.py")
ICONO = os.path.join(BASE, "chiwiro.ico")
ENV = os.path.join(BASE, ".env")

MAX_LINEAS_LOG = 600

# Paleta parecida a la de Discord, para que combine con lo que el bot hace.
FONDO = "#1e1f22"
PANEL = "#2b2d31"
TEXTO = "#dbdee1"
TENUE = "#949ba4"
ACENTO = "#5865f2"
VERDE = "#23a55a"
ROJO = "#f23f43"
AMARILLO = "#f0b232"


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


class ChiwiroApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proceso = None
        self.cola = queue.Queue()
        self.lineas = 0

        root.title("Chiwiro Music")
        root.configure(bg=FONDO)
        root.geometry("640x470")
        root.minsize(520, 360)
        if os.path.exists(ICONO):
            try:
                root.iconbitmap(default=ICONO)
            except tk.TclError:
                pass
        root.protocol("WM_DELETE_WINDOW", self.al_cerrar)

        self._construir_interfaz()
        self._revisar_cola()

        # "Abrirla y que se ejecute todo": arranca solo al abrir la ventana.
        root.after(300, self.iniciar)

    # ------------------------------------------------------------------ UI

    def _construir_interfaz(self):
        fuente_ui = tkfont.Font(family="Segoe UI", size=10)
        fuente_estado = tkfont.Font(family="Segoe UI", size=12, weight="bold")
        fuente_log = tkfont.Font(family="Consolas", size=9)

        cabecera = tk.Frame(self.root, bg=PANEL, padx=14, pady=12)
        cabecera.pack(fill="x")

        self.punto = tk.Label(cabecera, text="●", font=fuente_estado, bg=PANEL, fg=TENUE)
        self.punto.pack(side="left")
        self.estado = tk.Label(
            cabecera, text="  Detenido", font=fuente_estado, bg=PANEL, fg=TEXTO
        )
        self.estado.pack(side="left")

        self.detalle = tk.Label(cabecera, text="", font=fuente_ui, bg=PANEL, fg=TENUE)
        self.detalle.pack(side="right")

        botones = tk.Frame(self.root, bg=FONDO, padx=14, pady=12)
        botones.pack(fill="x")

        self.boton_encendido = self._boton(botones, "▶  Iniciar", self.alternar, ACENTO)
        self.boton_encendido.pack(side="left")
        self._boton(botones, "⚙  Configurar", self.abrir_env, PANEL).pack(side="left", padx=(8, 0))
        self._boton(botones, "📋  Copiar log", self.copiar_log, PANEL).pack(side="left", padx=(8, 0))
        self._boton(botones, "🗕  Ocultar", self.root.iconify, PANEL).pack(side="right")

        contenedor = tk.Frame(self.root, bg=FONDO)
        contenedor.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.log = tk.Text(
            contenedor, bg="#111214", fg=TEXTO, font=fuente_log, wrap="word",
            relief="flat", padx=10, pady=8, insertbackground=TEXTO, state="disabled",
        )
        barra = tk.Scrollbar(contenedor, command=self.log.yview, bg=PANEL)
        self.log.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self.log.tag_configure("hora", foreground=TENUE)
        self.log.tag_configure("error", foreground=ROJO)
        self.log.tag_configure("aviso", foreground=AMARILLO)
        self.log.tag_configure("ok", foreground=VERDE)

    def _boton(self, padre, texto, comando, color):
        return tk.Button(
            padre, text=texto, command=comando, bg=color, fg=TEXTO,
            activebackground=color, activeforeground=TEXTO, relief="flat",
            font=tkfont.Font(family="Segoe UI", size=10), padx=14, pady=6,
            cursor="hand2", borderwidth=0,
        )

    def escribir(self, texto, etiqueta=None):
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M  "), "hora")
        self.log.insert("end", texto.rstrip() + "\n", etiqueta or ())
        self.lineas += 1
        if self.lineas > MAX_LINEAS_LOG:
            self.log.delete("1.0", f"{self.lineas - MAX_LINEAS_LOG + 1}.0")
            self.lineas = MAX_LINEAS_LOG
        self.log.configure(state="disabled")
        self.log.see("end")

    def _poner_estado(self, texto, color, detalle=""):
        self.punto.configure(fg=color)
        self.estado.configure(text=f"  {texto}")
        self.detalle.configure(text=detalle)

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
            self.escribir(
                "No encontré el entorno virtual (venv). Abre una terminal en esta "
                "carpeta y ejecuta:  python -m venv venv", "error"
            )
            self.escribir(
                "Después:  venv\\Scripts\\pip install -r requirements.txt", "error"
            )
            return

        if not token_configurado():
            self._poner_estado("Falta configurar", AMARILLO)
            self.escribir("El archivo .env no tiene el token del bot.", "aviso")
            self.escribir(
                'Haz clic en "⚙ Configurar", pega el token en DISCORD_TOKEN=, guarda '
                "y vuelve a darle a Iniciar.", "aviso"
            )
            self.escribir(
                "El token se saca de discord.com/developers/applications → tu app "
                "→ Bot → Reset Token.", "aviso"
            )
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

        self._poner_estado("Conectando...", AMARILLO)
        self.boton_encendido.configure(text="⏹  Detener", bg=ROJO)
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

    def _procesar_linea(self, linea):
        limpia = linea.rstrip()
        if not limpia:
            return

        etiqueta = None
        if "[ERROR]" in limpia or "Traceback" in limpia or "Error" in limpia:
            etiqueta = "error"
        elif "[WARNING]" in limpia:
            etiqueta = "aviso"

        if "Conectado como" in limpia:
            nombre = limpia.split("Conectado como", 1)[1].split("(id=")[0].strip()
            self._poner_estado("En línea", VERDE, nombre)
            etiqueta = "ok"
        elif "Servidores:" in limpia:
            servidores = limpia.split("Servidores:", 1)[1].strip()
            self.detalle.configure(text=servidores[:60])
        elif "No se encontró DISCORD_TOKEN" in limpia:
            self._poner_estado("Falta configurar", AMARILLO)
            etiqueta = "error"

        # Le sacamos el prefijo del logging, que en una ventana propia sobra.
        for marca in ("[INFO] ", "[WARNING] ", "[ERROR] "):
            if marca in limpia:
                limpia = limpia.split(marca, 1)[1]
                break

        self.escribir(limpia, etiqueta)

    def _proceso_termino(self, codigo):
        self.proceso = None
        self.boton_encendido.configure(text="▶  Iniciar", bg=ACENTO)
        if codigo == 0:
            self._poner_estado("Detenido", TENUE)
            self.escribir("El bot se detuvo.", "aviso")
        else:
            self._poner_estado("Se cerró con error", ROJO)
            self.escribir(
                f"El bot se cerró con código {codigo}. Mira el log de arriba "
                f"para ver qué pasó.", "error"
            )

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
    # ponga nuestro ícono en la barra de tareas.
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
