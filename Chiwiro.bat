@echo off
REM Este archivo arranca el bot de música. Doble clic y listo.
REM Tiene que estar guardado en la misma carpeta que bot.py (F:\Music_Bot).

cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
    echo No se encontro el entorno virtual "venv" en esta carpeta.
    echo Corre primero: python -m venv venv
    echo y despues:     venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

echo Iniciando Chiwiro Music...
venv\Scripts\python.exe bot.py

REM Si el bot se cierra o tira un error, dejamos la ventana abierta
REM para poder leer el mensaje antes de que se cierre solo.
echo.
echo El bot se detuvo. Presiona una tecla para cerrar esta ventana.
pause >nul