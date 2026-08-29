# -*- coding: utf-8 -*-
"""Crea el acceso directo de Chiwiro Music (escritorio y carpeta del proyecto).

Lo importante acá es el AppUserModelID. Sin él, Windows trata al icono
anclado y a la ventana abierta como dos cosas distintas, y aparecen DOS
botones en la barra de tareas al abrir la app. Poniéndole el mismo ID que
la app se declara a sí misma (ver chiwiro_app.py), Windows los une en uno.

El .lnk apunta a pythonw.exe (sin consola) del venv.

Uso:  venv\\Scripts\\python.exe tools\\create_shortcut.py
"""
import os

import pythoncom
import win32com.client
from win32com.propsys import propsys, pscon

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESTINO_PYTHONW = os.path.join(BASE, "venv", "Scripts", "pythonw.exe")
GUION = "chiwiro_app.py"
ICONO = os.path.join(BASE, "chiwiro.ico")

# Tiene que ser idéntico al de chiwiro_app.py
APP_ID = "Chiwiro.Music.Bot"

# GETPROPERTYSTOREFLAGS.GPS_READWRITE, que pywin32 no expone como constante.
GPS_READWRITE = 0x2

NOMBRE = "Chiwiro Music.lnk"


def _escritorio() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop")


def crear(ruta_lnk: str):
    shell = win32com.client.Dispatch("WScript.Shell")
    atajo = shell.CreateShortCut(ruta_lnk)
    atajo.TargetPath = DESTINO_PYTHONW
    atajo.Arguments = GUION
    atajo.WorkingDirectory = BASE
    atajo.IconLocation = f"{ICONO},0"
    atajo.Description = "Chiwiro Music - bot de música para Discord"
    atajo.WindowStyle = 1
    atajo.save()

    # WScript.Shell no sabe de AppUserModelID, así que lo escribimos después
    # directamente en las propiedades del archivo.
    almacen = propsys.SHGetPropertyStoreFromParsingName(
        ruta_lnk, None, GPS_READWRITE, propsys.IID_IPropertyStore
    )
    almacen.SetValue(pscon.PKEY_AppUserModel_ID,
                     propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    almacen.Commit()

    print(f"  creado: {ruta_lnk}")


def main():
    for carpeta in (BASE, _escritorio()):
        if os.path.isdir(carpeta):
            crear(os.path.join(carpeta, NOMBRE))

    print(f"\nAppUserModelID: {APP_ID}")
    print("Si ya lo tenías anclado, desánclalo y vuelve a anclarlo para")
    print("que Windows tome el ID nuevo.")


if __name__ == "__main__":
    main()
