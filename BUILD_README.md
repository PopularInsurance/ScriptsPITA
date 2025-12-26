Instrucciones para crear un ejecutable de Windows y usarlo desde Power Automate
--------------------------------------------------------

1) Requisitos
   - Python 3 instalado (ejecutable `py` en PATH)
   - Conexión a internet para instalar PyInstaller

2) Construir el ejecutable (Windows)
   - Abrir PowerShell o CMD en la carpeta del proyecto (donde está `run_pipeline.py`)
   - Ejecutar:

```powershell
py -3 -m pip install --user pyinstaller
py -3 -m PyInstaller --onefile --name CotizacionesPipeline run_pipeline.py
```

   - Resultado: `dist\CotizacionesPipeline.exe`

3) Empaquetado y despliegue
   - Si usas `--onefile`, el exe es autónomo. Copia `dist\CotizacionesPipeline.exe` a la máquina donde Power Automate ejecute el proceso.
   - Si tu flujo depende de archivos externos (por ejemplo carpetas con PDFs), coloca esas carpetas en rutas absolutas conocidas y ajusta `CARPETAS` en `pipeline.py` si es necesario.

4) Ejecutar desde Power Automate (Windows)
   - Usa la acción que ejecute un programa o un script en la máquina (por ejemplo "Run a program" o un flujo que ejecute un PowerShell remoto).
   - Ejemplo de comando (PowerShell):

```powershell
Start-Process -FilePath "C:\ruta\a\CotizacionesPipeline.exe" -NoNewWindow -Wait
```

   - Alternativa simple (Command line):

```
C:\ruta\a\CotizacionesPipeline.exe
```

5) Notas importantes
   - Si Power Automate ejecuta la tarea en un servicio o cuenta con permisos limitados, verifica permisos de acceso a las carpetas `Desktop\BotPITA` u otras rutas usadas por `pipeline.py`.
   - Recomiendo probar manualmente el `.exe` en la misma cuenta/entorno que Power Automate antes de automatizar.

6) Archivos añadidos
   - `run_pipeline.py` : entrypoint para empaquetar y ejecutar el pipeline
   - `build_exe.bat`   : script que ejecuta PyInstaller y genera el .exe
   - `requirements.txt`: contiene `pyinstaller`
   - `BUILD_README.md`  : este archivo con instrucciones
