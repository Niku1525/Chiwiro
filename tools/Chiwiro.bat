@echo off
REM Arranca el bot en una consola, sin la app de escritorio.
REM Sirve para depurar: aca se ve la salida cruda de yt-dlp y de discord.py.
REM Para el uso normal esta la app (doble clic en el icono de Chiwiro).

REM Este .bat vive en tools\, asi que subimos a la raiz del proyecto.
cd /d "%~dp0.."

if not exist venv\Scripts\python.exe (
    echo No se encontro el entorno virtual "venv" en la carpeta del proyecto.
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
