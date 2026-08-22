# -*- coding: utf-8 -*-
"""Activa o desactiva que Chiwiro arranque solo al prender la PC.

Usa la carpeta de Inicio de Windows, no el registro. Es a propósito:

- No pide permisos de administrador.
- Es de tu usuario nada más, no del sistema.
- Se ve y se apaga desde Configuración → Aplicaciones → Inicio, o en el
  Administrador de tareas → pestaña Inicio.
- Para quitarlo alcanza con borrar un archivo (o correr este script con
  "desactivar"), sin tocar nada delicado.

El acceso directo abre la app con --minimizado: el bot se enciende igual,
pero la ventana arranca guardada en la barra de tareas en vez de saltar
sola cada vez que enciendes la computadora.

Uso:
    venv\\Scripts\\python.exe herramientas\\inicio_con_windows.py activar
    venv\\Scripts\\python.exe herramientas\\inicio_con_windows.py desactivar
    venv\\Scripts\\python.exe herramientas\\inicio_con_windows.py estado
"""
import os
import sys

import pythoncom
import win32com.client
from win32com.propsys import propsys, pscon

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHONW = os.path.join(BASE, "venv", "Scripts", "pythonw.exe")
ICONO = os.path.join(BASE, "chiwiro.ico")

APP_ID = "Chiwiro.Music.Bot"
NOMBRE = "Chiwiro Music.lnk"

# GETPROPERTYSTOREFLAGS.GPS_READWRITE, que pywin32 no expone como constante.
GPS_READWRITE = 0x2


def carpeta_inicio() -> str:
    return os.path.join(
        os.environ["APPDATA"],
        "Microsoft", "Windows", "Start Menu", "Programs", "Startup",
    )


def ruta_atajo() -> str:
    return os.path.join(carpeta_inicio(), NOMBRE)


def activar():
    destino = ruta_atajo()

    shell = win32com.client.Dispatch("WScript.Shell")
    atajo = shell.CreateShortCut(destino)
    atajo.TargetPath = PYTHONW
    atajo.Arguments = "chiwiro_app.py --minimizado"
    atajo.WorkingDirectory = BASE
    atajo.IconLocation = f"{ICONO},0"
    atajo.Description = "Chiwiro Music - arranca con Windows"
    atajo.WindowStyle = 7          # minimizado (Tk igual necesita el flag)
    atajo.save()

    almacen = propsys.SHGetPropertyStoreFromParsingName(
        destino, None, GPS_READWRITE, propsys.IID_IPropertyStore
    )
    almacen.SetValue(pscon.PKEY_AppUserModel_ID,
                     propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    almacen.Commit()

    print("Arranque automático ACTIVADO.")
    print(f"  {destino}")
    print("\nLa próxima vez que enciendas la PC, Chiwiro se conecta solo.")
    print("La ventana arranca minimizada en la barra de tareas.")


def desactivar():
    destino = ruta_atajo()
    if os.path.exists(destino):
        os.remove(destino)
        print("Arranque automático DESACTIVADO.")
        print(f"  borrado: {destino}")
    else:
        print("No estaba activado, no hay nada que borrar.")


def estado():
    destino = ruta_atajo()
    if os.path.exists(destino):
        shell = win32com.client.Dispatch("WScript.Shell")
        atajo = shell.CreateShortCut(destino)
        print("Arranque automático: ACTIVADO")
        print(f"  archivo : {destino}")
        print(f"  ejecuta : {atajo.TargetPath} {atajo.Arguments}")
    else:
        print("Arranque automático: desactivado")


def main():
    acciones = {"activar": activar, "desactivar": desactivar, "estado": estado}
    accion = sys.argv[1].lower() if len(sys.argv) > 1 else "estado"

    if accion not in acciones:
        print(f"Acción desconocida: {accion!r}")
        print("Usa una de: activar, desactivar, estado")
        raise SystemExit(1)

    acciones[accion]()


if __name__ == "__main__":
    main()
