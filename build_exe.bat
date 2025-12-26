@echo off
REM Script para generar un ejecutable con PyInstaller (Windows)
REM Ejecutar desde el directorio: c:\Users\PR65368\Downloads\script-popular-master\

echo Instalando PyInstaller (si falta)...
py -3 -m pip install --user pyinstaller

echo Construyendo ejecutable (onefile)...
py -3 -m PyInstaller --onefile --name CotizacionesPipeline run_pipeline.py

echo Finalizado. Ejecutable en dist\CotizacionesPipeline.exe
pause
