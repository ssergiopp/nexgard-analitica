@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creando entorno e instalando dependencias, solo la primera vez...
  python -m venv .venv || goto :error
  ".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error
)
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn app:app --app-dir backend --port 8000
echo.
echo El servidor se detuvo. Si fue un error, revisa el mensaje de arriba.
pause
goto :eof
:error
echo No se pudo preparar el entorno. Verifica que Python 3.10+ este instalado y en el PATH.
if exist .venv rmdir /s /q .venv
pause