import os

import pythoncom
import win32com.client
from win32com.propsys import propsys, pscon

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHONW_PATH = os.path.join(BASE, "venv", "Scripts", "pythonw.exe")
SCRIPT = r"app\chiwiro_app.py"
ICON = os.path.join(BASE, "assets", "chiwiro.ico")

APP_ID = "Chiwiro.Music.Bot"

GPS_READWRITE = 0x2

SHORTCUT_NAME = "Chiwiro Music.lnk"


def _desktop() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop")


def create(lnk_path: str):
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(lnk_path)
    shortcut.TargetPath = PYTHONW_PATH
    shortcut.Arguments = SCRIPT
    shortcut.WorkingDirectory = BASE
    shortcut.IconLocation = f"{ICON},0"
    shortcut.Description = "Chiwiro Music - bot de música para Discord"
    shortcut.WindowStyle = 1
    shortcut.save()

    store = propsys.SHGetPropertyStoreFromParsingName(
        lnk_path, None, GPS_READWRITE, propsys.IID_IPropertyStore
    )
    store.SetValue(pscon.PKEY_AppUserModel_ID,
                   propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()

    print(f"  creado: {lnk_path}")


def main():
    for folder in (BASE, _desktop()):
        if os.path.isdir(folder):
            create(os.path.join(folder, SHORTCUT_NAME))

    print(f"\nAppUserModelID: {APP_ID}")
    print("Si ya lo tenías anclado, desánclalo y vuelve a anclarlo para")
    print("que Windows tome el ID nuevo.")


if __name__ == "__main__":
    main()
