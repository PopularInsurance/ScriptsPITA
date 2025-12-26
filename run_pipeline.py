"""
Punto de entrada mínimo para empaquetar `pipeline.py` en un ejecutable.

Uso:
    python run_pipeline.py

Cuando se empaqueta con PyInstaller, este archivo se usará como script principal.
"""
import os
import sys

# Asegurar que el directorio actual esté en sys.path (útil durante desarrollo)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from pipeline import ejecutar_pipeline


if __name__ == "__main__":
    ejecutar_pipeline()
