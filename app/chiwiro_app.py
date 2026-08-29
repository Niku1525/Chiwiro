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

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = os.path.join(BASE, "venv", "Scripts", "python.exe")
BOT = os.path.join(BASE, "bot.py")
ICON = os.path.join(BASE, "assets", "chiwiro.ico")
BIG_ICON = os.path.join(BASE, "assets", "cinnamoroll-100.ico")
ENV = os.path.join(BASE, ".env")
CONFIG = os.path.join(BASE, "data", "app_config.json")

APP_ID = "Chiwiro.Music.Bot"

MAX_LOG_LINES = 600

THEMES = {
    "light": {
        "bg": "#fdf1f6",
        "panel": "#ffffff",
        "cloud": "#fbe4ef",
        "deco": "#f9d6e6",
        "title": "#8d6c9f",
        "fg": "#7c5f70",
        "muted": "#bda2b2",
        "scroll_track": "#f6e8f0",
        "primary": "#e58bb0",
        "primary_hover": "#ef9fc2",
        "primary_fg": "#ffffff",
        "stop": "#f0a3c4",
        "stop_hover": "#f6b8d3",
        "stop_fg": "#7a3352",
        "cream": "#f9eede",
        "cream_hover": "#f3e3cd",
        "cream_fg": "#96733f",
        "lilac": "#f2e9f7",
        "lilac_hover": "#e6d6f0",
        "lilac_fg": "#8d6c9f",
        "pink": "#fde9f1",
        "pink_hover": "#f9cede",
        "pink_fg": "#c4718f",
        "ok": "#4f9b7a",
        "ok_bg": "#e6f6ee",
        "warn": "#b98533",
        "warn_bg": "#fbf1e3",
        "error": "#c96f6f",
        "error_bg": "#fdeeee",
        "idle_bg": "#f6e8f0",
    },
    "dark": {
        "bg": "#221a28",
        "panel": "#2d2234",
        "cloud": "#372940",
        "deco": "#3f2f4a",
        "title": "#f0b8d4",
        "fg": "#e9d9e4",
        "muted": "#a288ab",
        "scroll_track": "#372940",
        "primary": "#e58bb0",
        "primary_hover": "#f0a3c4",
        "primary_fg": "#2b1f31",
        "stop": "#4d3247",
        "stop_hover": "#5d3d57",
        "stop_fg": "#f6b8d3",
        "cream": "#3d3020",
        "cream_hover": "#4b3b28",
        "cream_fg": "#f0d9b8",
        "lilac": "#382a42",
        "lilac_hover": "#453352",
        "lilac_fg": "#d9b8ec",
        "pink": "#3d2839",
        "pink_hover": "#4d3247",
        "pink_fg": "#f0a3c4",
        "ok": "#8fd9b6",
        "ok_bg": "#26382f",
        "warn": "#e8c07d",
        "warn_bg": "#3a3125",
        "error": "#f0a0a0",
        "error_bg": "#3d2a2a",
        "idle_bg": "#372940",
    },
}


def token_is_set() -> bool:
    try:
        with open(ENV, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DISCORD_TOKEN=") and line.split("=", 1)[1].strip():
                    return True
    except OSError:
        pass
    return False


def read_config() -> dict:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_config(data: dict):
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def orphan_bots() -> list:
    found = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if process.info["pid"] == os.getpid():
                continue
            if not (process.info["name"] or "").lower().startswith("python"):
                continue
            cmdline = process.info["cmdline"] or []
            if any(a.replace("/", "\\").endswith(BOT.replace("/", "\\"))
                   or a == BOT for a in cmdline):
                found.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def rounded_rect(canvas, x0, y0, x1, y1, radius, **kwargs):
    points = [
        x0 + radius, y0, x1 - radius, y0, x1, y0, x1, y0 + radius,
        x1, y1 - radius, x1, y1, x1 - radius, y1, x0 + radius, y1,
        x0, y1, x0, y1 - radius, x0, y0 + radius, x0, y0,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class RoundButton(tk.Canvas):
    def __init__(self, parent, text, command, bg, fg, page_bg,
                 bg_hover=None, width=None, font=None, **kw):
        self.font = font or tkfont.Font(family="Segoe UI", size=10, weight="bold")
        width = width or self.font.measure(text) + 36
        super().__init__(parent, width=width, height=38, bg=page_bg,
                         highlightthickness=0, bd=0, cursor="hand2", **kw)
        self.command = command
        self.bg = bg
        self.bg_hover = bg_hover or bg
        self.enabled = True

        self.shape = rounded_rect(self, 1, 1, width - 1, 37, 15, fill=bg, outline="")
        self.tag = self.create_text(width / 2, 19, text=text,
                                    fill=fg, font=self.font)

        self.bind("<Enter>", lambda _: self.itemconfigure(self.shape, fill=self.bg_hover))
        self.bind("<Leave>", lambda _: self.itemconfigure(self.shape, fill=self.bg))
        self.bind("<Button-1>", lambda _: self.command and self.command())

    def set_state(self, text=None, bg=None, fg=None, bg_hover=None):
        if text is not None:
            self.itemconfigure(self.tag, text=text)
        if bg is not None:
            self.bg = bg
            self.itemconfigure(self.shape, fill=bg)
        if bg_hover is not None:
            self.bg_hover = bg_hover
        if fg is not None:
            self.itemconfigure(self.tag, fill=fg)


class ChiwiroApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.process = None
        self.queue = queue.Queue()
        self.entries = []

        self.config = read_config()
        self.theme = self.config.get("theme", "light")

        self._status_text = "durmiendo~"
        self._status_key = "idle"
        self._status_detail = ""

        root.title("Chiwiro")
        root.geometry("660x520")
        root.minsize(560, 430)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._load_fonts()
        self._load_icon()
        self._build_ui()
        self._drain_queue()

        root.after(400, self.start)

    @property
    def c(self) -> dict:
        return THEMES[self.theme]


    def _load_icon(self):
        if os.path.exists(ICON):
            try:
                self.root.iconbitmap(default=ICON)
            except tk.TclError:
                pass
        self.root.after(60, self._sharp_icon)

        try:
            image = Image.open(BIG_ICON).convert("RGBA").resize((76, 76), Image.LANCZOS)
            self.icon_image = ImageTk.PhotoImage(image)
        except Exception:
            self.icon_image = None

    def _sharp_icon(self):
        try:
            import ctypes
            user32 = ctypes.windll.user32
            try:
                hwnd = int(self.root.wm_frame(), 16)
            except (ValueError, tk.TclError):
                hwnd = self.root.winfo_id()

            IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x0010, 0x0080
            for tam, cual in ((16, 0), (32, 1)):
                handle = user32.LoadImageW(None, ICON, IMAGE_ICON, tam, tam,
                                           LR_LOADFROMFILE)
                if handle:
                    user32.SendMessageW(hwnd, WM_SETICON, cual, handle)
        except Exception:
            pass


    def _load_fonts(self):
        families = set(tkfont.families())

        def pick(*opciones):
            for o in opciones:
                if o in families:
                    return o
            return "Segoe UI"

        title = pick("Ink Free", "Comic Sans MS", "Segoe UI")
        body = pick("Segoe UI", "Candara")

        self.f_title = tkfont.Font(family=title, size=23)
        self.f_sub = tkfont.Font(family=body, size=9)
        self.f_status = tkfont.Font(family=body, size=10, weight="bold")
        self.f_button = tkfont.Font(family=body, size=10, weight="bold")
        self.f_log = tkfont.Font(family=body, size=9)
        self.f_time = tkfont.Font(family=pick("Consolas", "Courier New"), size=8)

    def _build_ui(self):
        c = self.c
        self.root.configure(bg=c["bg"])

        self.header = tk.Canvas(self.root, bg=c["bg"], height=124,
                                highlightthickness=0, bd=0)
        self.header.pack(fill="x")
        self.header.bind("<Configure>", self._draw_header)

        self.button_bar = tk.Frame(self.root, bg=c["bg"])
        self.button_bar.pack(fill="x", padx=22, pady=(2, 12))
        b = self.button_bar

        self.power_button = RoundButton(
            b, "♡   Iniciar", self.toggle, c["primary"], c["primary_fg"],
            c["bg"], bg_hover=c["primary_hover"], width=142, font=self.f_button)
        self.power_button.pack(side="left")

        RoundButton(b, "Configurar", self.open_env, c["cream"], c["cream_fg"],
                    c["bg"], bg_hover=c["cream_hover"],
                    font=self.f_button).pack(side="left", padx=(10, 0))
        RoundButton(b, "Copiar log", self.copy_log, c["lilac"], c["lilac_fg"],
                    c["bg"], bg_hover=c["lilac_hover"],
                    font=self.f_button).pack(side="left", padx=(10, 0))

        RoundButton(b, "Ocultar", self.root.iconify, c["pink"], c["pink_fg"],
                    c["bg"], bg_hover=c["pink_hover"],
                    font=self.f_button).pack(side="right")
        theme_label = "☾  Oscuro" if self.theme == "light" else "☀  Claro"
        RoundButton(b, theme_label, self.switch_theme, c["lilac"], c["lilac_fg"],
                    c["bg"], bg_hover=c["lilac_hover"], width=104,
                    font=self.f_button).pack(side="right", padx=(0, 10))

        self.log_wrapper = tk.Frame(self.root, bg=c["bg"])
        self.log_wrapper.pack(fill="both", expand=True, padx=22, pady=(0, 20))

        self.log_canvas = tk.Canvas(self.log_wrapper, bg=c["bg"],
                                    highlightthickness=0, bd=0)
        self.log_canvas.pack(fill="both", expand=True)
        self.log_canvas.bind("<Configure>", self._draw_log_panel)

        content = tk.Frame(self.log_canvas, bg=c["panel"])
        self.log = tk.Text(
            content, bg=c["panel"], fg=c["fg"], font=self.f_log, wrap="word",
            relief="flat", padx=6, pady=4, insertbackground=c["fg"],
            state="disabled", borderwidth=0, highlightthickness=0,
            spacing1=2, spacing3=2, cursor="arrow",
        )
        self.scrollbar = tk.Scrollbar(content, command=self.log.yview,
                                      bg=c["panel"], troughcolor=c["scroll_track"],
                                      activebackground=c["primary"], relief="flat",
                                      borderwidth=0, width=10)
        self.log.configure(yscrollcommand=self._sync_scrollbar)
        self.scrollbar.pack(side="right", fill="y", pady=6)
        self.log.pack(side="left", fill="both", expand=True)
        self.log_window = self.log_canvas.create_window(0, 0, window=content, anchor="nw")

        self.log.tag_configure("time", foreground=c["muted"], font=self.f_time)
        self.log.tag_configure("normal", foreground=c["fg"])
        self.log.tag_configure("ok", foreground=c["ok"])
        self.log.tag_configure("warn", foreground=c["warn"])
        self.log.tag_configure("error", foreground=c["error"])

        self._render_log()


    def _heart(self, canvas, x, y, tam, color):
        canvas.create_text(x, y, text="♡", fill=color,
                           font=tkfont.Font(family="Segoe UI Symbol", size=tam))

    def _cloud(self, canvas, cx, cy, scale, color):
        for dx, dy, r in [(-16, 4, 13), (0, -2, 18), (17, 5, 12), (0, 10, 15)]:
            canvas.create_oval(cx + (dx - r) * scale, cy + (dy - r) * scale,
                               cx + (dx + r) * scale, cy + (dy + r) * scale,
                               fill=color, outline="")

    def _draw_header(self, evento=None):
        c = self.c
        canvas = self.header
        width = evento.width if evento else canvas.winfo_width()
        canvas.delete("all")

        for cx, cy, scale in [(width - 78, 24, 1.1), (width - 152, 66, 0.75),
                              (width - 214, 20, 0.55)]:
            self._cloud(canvas, cx, cy, scale, c["cloud"])
        for x, y, tam in [(width - 250, 62, 13), (width - 118, 100, 10),
                          (width - 46, 104, 15), (14, 30, 11), (10, 96, 14)]:
            self._heart(canvas, x, y, tam, c["deco"])

        rounded_rect(canvas, 22, 10, max(width - 22, 220), 108, 26,
                     fill=c["panel"], outline="")

        if self.icon_image is not None:
            canvas.create_image(46, 59, image=self.icon_image, anchor="w")

        canvas.create_text(134, 44, text="Chiwiro", anchor="w",
                           fill=c["title"], font=self.f_title)
        canvas.create_text(136, 74, text="♡  Tu bot de música en Discord  ♡",
                           anchor="w", fill=c["muted"], font=self.f_sub)

        self._draw_pill(width)

    def _draw_pill(self, width=None):
        c = self.c
        canvas = self.header
        width = width or canvas.winfo_width()
        canvas.delete("pastilla")

        colors = {
            "idle": (c["muted"], c["idle_bg"]),
            "waking": (c["warn"], c["warn_bg"]),
            "online": (c["ok"], c["ok_bg"]),
            "error": (c["error"], c["error_bg"]),
        }
        color, bg = colors.get(self._status_key, colors["idle"])

        x1 = width - 42
        x0 = x1 - self.f_status.measure(self._status_text) - 46
        rounded_rect(canvas, x0, 32, x1, 62, 15, fill=bg, outline="", tags="pastilla")
        canvas.create_oval(x0 + 16, 43, x0 + 26, 53, fill=color, outline="",
                           tags="pastilla")
        canvas.create_text(x0 + 33, 47, text=self._status_text, anchor="w",
                           fill=color, font=self.f_status, tags="pastilla")
        if self._status_detail:
            canvas.create_text(x1, 80, text=self._status_detail[:44], anchor="e",
                               fill=c["muted"], font=self.f_sub, tags="pastilla")

    def _draw_log_panel(self, evento=None):
        canvas = self.log_canvas
        width = evento.width if evento else canvas.winfo_width()
        height = evento.height if evento else canvas.winfo_height()
        canvas.delete("bg")
        rounded_rect(canvas, 0, 0, width, height, 24, fill=self.c["panel"],
                     outline="", tags="bg")
        canvas.tag_lower("bg")
        canvas.coords(self.log_window, 16, 18)
        canvas.itemconfigure(self.log_window, width=max(width - 32, 50),
                             height=max(height - 34, 50))

    def _sync_scrollbar(self, first, last):
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.scrollbar.pack_forget()
        elif not self.scrollbar.winfo_ismapped():
            self.scrollbar.pack(side="right", fill="y", pady=6, before=self.log)
        self.scrollbar.set(first, last)


    def switch_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.config["theme"] = self.theme
        write_config(self.config)

        for child in self.root.winfo_children():
            child.destroy()
        self._build_ui()
        self.root.update_idletasks()
        self._draw_header()
        self._draw_log_panel()

        if self.running:
            self.power_button.set_state(
                text="■   Detener", bg=self.c["stop"],
                bg_hover=self.c["stop_hover"], fg=self.c["stop_fg"])


    BULLETS = {"ok": "♡ ", "warn": "✿ ", "error": "✖ ", "normal": ""}

    def write(self, text, tag="normal"):
        self.entries.append((time.strftime("%H:%M"), text.rstrip(), tag))
        if len(self.entries) > MAX_LOG_LINES:
            self.entries = self.entries[-MAX_LOG_LINES:]
            self._render_log()
            return
        self._render_entry(self.entries[-1])
        self.log.see("end")

    def _render_entry(self, entry):
        when, text, tag = entry
        self.log.configure(state="normal")
        self.log.insert("end", when + "  ", "time")
        self.log.insert("end", self.BULLETS.get(tag, "") + text + "\n", tag)
        self.log.configure(state="disabled")

    def _render_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        for entry in self.entries:
            self._render_entry(entry)
        self.log.see("end")

    def _set_status(self, text, key, detail=None):
        self._status_text = text
        self._status_key = key
        if detail is not None:
            self._status_detail = detail
        self._draw_pill()


    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def toggle(self):
        self.stop() if self.running else self.start()

    def start(self):
        if self.running:
            return

        if not os.path.exists(PYTHON):
            self.write("No encontré el entorno virtual (venv). Abre una terminal "
                       "en esta carpeta y ejecuta:  python -m venv venv", "error")
            self.write("Después:  venv\\Scripts\\pip install -r requirements.txt",
                       "error")
            return

        if not token_is_set():
            self._set_status("falta el token", "waking")
            self.write("El archivo .env no tiene el token del bot.", "warn")
            self.write('Haz clic en "Configurar", pega el token en DISCORD_TOKEN=, '
                       "guarda y vuelve a darle a Iniciar.", "warn")
            self.write("El token se saca de discord.com/developers/applications "
                       "→ tu app → Bot → Reset Token.", "warn")
            return

        orphans = orphan_bots()
        if orphans:
            self.write(f"Había {len(orphans)} instancia(s) del bot dando "
                       f"vueltas de antes. Las cierro para que no conteste "
                       f"doble.", "warn")
            for process in orphans:
                try:
                    process.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            psutil.wait_procs(orphans, timeout=5)

        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"

        flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP

        try:
            self.process = subprocess.Popen(
                [PYTHON, "-u", BOT], cwd=BASE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, env=env, creationflags=flags,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
        except OSError as e:
            self.write(f"No pude arrancar el bot: {e}", "error")
            return

        threading.Thread(target=self._read_output, args=(self.process,),
                         daemon=True).start()

        self._set_status("despertando...", "waking")
        self.power_button.set_state(text="■   Detener", bg=self.c["stop"],
                                    bg_hover=self.c["stop_hover"],
                                    fg=self.c["stop_fg"])
        self.write("Arrancando el bot...", "ok")

    def _read_output(self, process):
        for line in process.stdout:
            self.queue.put(("log", line))
        process.stdout.close()
        self.queue.put(("fin", process.wait()))

    def stop(self):
        if not self.running:
            return
        self.write("Deteniendo el bot...", "warn")
        try:
            self.process.send_signal(signal.CTRL_BREAK_EVENT)
            self.process.wait(timeout=6)
        except Exception:
            try:
                self.process.terminate()
                self.process.wait(timeout=4)
            except Exception:
                self.process.kill()


    def _drain_queue(self):
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "log":
                    self._handle_line(payload)
                else:
                    self._process_ended(payload)
        except queue.Empty:
            pass
        self.root.after(120, self._drain_queue)

    @staticmethod
    def _is_noise(line: str) -> bool:
        if "[INFO]" not in line:
            return False
        rest = line.split("[INFO]", 1)[1].strip()
        return rest.split(":", 1)[0].strip().startswith("discord.")

    def _handle_line(self, line):
        clean = line.rstrip()
        if not clean or self._is_noise(clean):
            return

        tag = "normal"
        if "[ERROR]" in clean or "Traceback" in clean:
            tag = "error"
        elif "[WARNING]" in clean:
            tag = "warn"

        if "Conectado como" in clean:
            name = clean.split("Conectado como", 1)[1].split("(id=")[0].strip()
            self._set_status("en línea ♡", "online", name)
            tag = "ok"
        elif "Servidores:" in clean:
            self._status_detail = clean.split("Servidores:", 1)[1].strip()
            self._draw_pill()
        elif "No se encontró DISCORD_TOKEN" in clean:
            self._set_status("falta el token", "waking")
            tag = "error"

        for marker in ("[INFO] ", "[WARNING] ", "[ERROR] "):
            if marker in clean:
                clean = clean.split(marker, 1)[1]
                name, sep, message = clean.partition(": ")
                if sep and " " not in name:
                    clean = message
                break

        self.write(clean, tag)

    def _process_ended(self, code):
        self.process = None
        self.power_button.set_state(text="♡   Iniciar", bg=self.c["primary"],
                                    bg_hover=self.c["primary_hover"],
                                    fg=self.c["primary_fg"])
        if code == 0:
            self._set_status("durmiendo~", "idle", "")
            self.write("El bot se detuvo. ¡Hasta la próxima!", "warn")
        else:
            self._set_status("se cayó :(", "error", "")
            self.write(f"El bot se cerró con código {code}. Mira el log de "
                       f"arriba para ver qué pasó.", "error")

    def open_env(self):
        if not os.path.exists(ENV):
            example = os.path.join(BASE, ".env.example")
            if os.path.exists(example):
                with open(example, encoding="utf-8") as src_file, \
                     open(ENV, "w", encoding="utf-8") as dst_file:
                    dst_file.write(src_file.read())
                self.write("Creé un .env nuevo a partir de .env.example.", "warn")
        try:
            os.startfile(ENV)
        except OSError:
            subprocess.Popen(["notepad.exe", ENV])

    def copy_log(self):
        self.root.clipboard_clear()
        self.root.clipboard_append("\n".join(
            f"{h}  {t}" for h, t, _ in self.entries))
        self.write("Log copiado al portapapeles.", "ok")

    def on_close(self):
        if self.running:
            self.stop()
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass

    root = tk.Tk()
    ChiwiroApp(root)

    if "--minimizado" in sys.argv:
        root.after(120, root.iconify)

    root.mainloop()


if __name__ == "__main__":
    main()
