import os
import sys

import pythoncom
import win32com.client
from win32com.propsys import propsys, pscon

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHONW_PATH = os.path.join(BASE, "venv", "Scripts", "pythonw.exe")
ICON = os.path.join(BASE, "assets", "chiwiro.ico")

APP_ID = "Chiwiro.Music.Bot"
SHORTCUT_NAME = "Chiwiro Music.lnk"

GPS_READWRITE = 0x2


def startup_folder() -> str:
    return os.path.join(
        os.environ["APPDATA"],
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )


def shortcut_path() -> str:
    return os.path.join(startup_folder(), SHORTCUT_NAME)


def enable():
    lnk_path = shortcut_path()

    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(lnk_path)
    shortcut.TargetPath = PYTHONW_PATH
    shortcut.Arguments = r"app\chiwiro_app.py --minimizado"
    shortcut.WorkingDirectory = BASE
    shortcut.IconLocation = f"{ICON},0"
    shortcut.Description = "Chiwiro Music - arranca con Windows"
    shortcut.WindowStyle = 7
    shortcut.save()

    store = propsys.SHGetPropertyStoreFromParsingName(
        lnk_path, None, GPS_READWRITE, propsys.IID_IPropertyStore
    )
    store.SetValue(pscon.PKEY_AppUserModel_ID,
                   propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()

    print("Arranque automático ACTIVADO.")
    print(f"  {lnk_path}")
    print("\nLa próxima vez que enciendas la PC, Chiwiro se conecta solo.")
    print("La ventana arranca minimizada en la barra de tareas.")


def disable():
    lnk_path = shortcut_path()
    if os.path.exists(lnk_path):
        os.remove(lnk_path)
        print("Arranque automático DESACTIVADO.")
        print(f"  borrado: {lnk_path}")
    else:
        print("No estaba activado, no hay nada que borrar.")


def status():
    lnk_path = shortcut_path()
    if os.path.exists(lnk_path):
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortCut(lnk_path)
        print("Arranque automático: ACTIVADO")
        print(f"  archivo : {lnk_path}")
        print(f"  ejecuta : {shortcut.TargetPath} {shortcut.Arguments}")
    else:
        print("Arranque automático: desactivado")


def main():
    actions = {"activar": enable, "desactivar": disable, "estado": status}
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "estado"

    if action not in actions:
        print(f"Acción desconocida: {action!r}")
        print("Usa una de: activar, desactivar, estado")
        raise SystemExit(1)

    actions[action]()


if __name__ == "__main__":
    main()
