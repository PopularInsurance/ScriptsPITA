"""
Inicializador de Estructura del Pipeline
=========================================
Crea las carpetas necesarias y mueve los PDFs existentes a Cotizaciones/

Ejecutar UNA VEZ antes de usar el pipeline por primera vez.

Uso:
    python inicializar_estructura.py
"""

import os
import shutil
from glob import glob
from datetime import datetime

# Carpetas a crear
CARPETAS = [
    "BotPITA/Inbox",
    "BotPITA/Processing_OCR",
    "BotPITA/Done_JSON",
    "BotPITA/Processing_TXT",
    "BotPITA/Error",
    "BotPITA/Logs",
    "BotPITA/Historial_OCR",
]

def main():
    print("="*60)
    print("INICIALIZADOR DE ESTRUCTURA DEL PIPELINE (AMPLIADO)")
    print("="*60)

    # --- Crear carpetas ---
    print("\n[1/2] Creando carpetas...")
    for carpeta in CARPETAS:
        if not os.path.exists(carpeta):
            os.makedirs(carpeta)
            print(f"  [OK] Creada: {carpeta}/")
        else:
            print(f"  [--] Ya existe: {carpeta}/")

    # --- Mover PDFs existentes (igual que antes) ---
    print("\n[2/2] Buscando PDFs en la raíz para mover...")

    # Buscar PDFs en la carpeta actual (raíz)
    pdfs_raiz = [f for f in glob("*.pdf") if not f.endswith("_OCR.pdf")]
    pdfs_ocr = glob("*_OCR.pdf")

    if pdfs_raiz:
        print(f"\n  Encontrados {len(pdfs_raiz)} PDFs originales:")
        for pdf in pdfs_raiz:
            destino = os.path.join("Cotizaciones", pdf)
            if not os.path.exists(destino):
                shutil.move(pdf, destino)
                print(f"    [OK] Movido: {pdf} -> Cotizaciones/")
            else:
                print(f"    [--] Ya existe en destino: {pdf}")
    else:
        print("  No hay PDFs originales en la raíz para mover.")

    if pdfs_ocr:
        print(f"\n  Encontrados {len(pdfs_ocr)} PDFs con OCR:")
        for pdf in pdfs_ocr:
            destino = os.path.join("Cotizaciones_OCR", pdf)
            if not os.path.exists(destino):
                shutil.move(pdf, destino)
                print(f"    [OK] Movido: {pdf} -> Cotizaciones_OCR/")
            else:
                print(f"    [--] Ya existe en destino: {pdf}")
    else:
        print("  No hay PDFs con OCR en la raíz para mover.")

    # --- Desplegar helper si no existe ---
    HELPER_NAME = "cotizaciones_temp_handler.py"
    HELPER_CONTENT = r'''
"""
cotizaciones_temp_handler.py

Helper para:
 - Agrupar PDFs colocados en la carpeta temporal (por ID en filename o prefijo)
 - Unir los PDFs de cada grupo a un solo PDF
 - Ejecutar OCR sobre el PDF unido (usando convertir_a_searchable)
 - Generar JSON y TXT usando las funciones de verificar_prestamos_v3
 - Guardar resultados en la estructura BotPITA

Ejecutar:
    python cotizaciones_temp_handler.py
"""

import os
import re
import sys
import json
import time
import shutil
from glob import glob
from datetime import datetime

# Intentar importar merge/ocr/reporte desde el repo
try:
    from PyPDF2 import PdfMerger
except Exception:
    PdfMerger = None

try:
    from convertir_a_searchable import convertir_pdf_a_searchable
except Exception:
    convertir_pdf_a_searchable = None

try:
    from verificar_prestamos_v3 import procesar_paquete, validar_consistencia, generar_reporte
except Exception:
    procesar_paquete = validar_consistencia = generar_reporte = None

# Carpetas (usar la estructura BotPITA)
CARPETAS = {
    "inbox": "BotPITA/Inbox",
    "ocr": "BotPITA/Processing_OCR",
    "done_json": "BotPITA/Done_JSON",
    "done_txt": "BotPITA/Processing_TXT",
    "error": "BotPITA/Error",
    "logs": "BotPITA/Logs",
    "historial": "BotPITA/Historial_OCR",
}

def find_group_key(filename):
    """
    Encontrar un ID para agrupar:
     - Primero intenta encontrar un número de 6-12 dígitos en el nombre
     - Si no, usa el prefijo antes del primer guion/underscore/espacio
    """
    base = os.path.basename(filename)
    m = re.search(r'(\d{6,12})', base)
    if m:
        return m.group(1)
    # fallback: prefix
    prefix = re.split(r'[-_\s]', os.path.splitext(base)[0])[0]
    return prefix.lower() if prefix else base

def merge_pdfs(file_list, output_path):
    if not PdfMerger:
        raise RuntimeError("PyPDF2 no disponible (PdfMerger). Instala PyPDF2.")
    merger = PdfMerger()
    for f in file_list:
        merger.append(f)
    with open(output_path, "wb") as fout:
        merger.write(fout)
    merger.close()

def ocr_pdf(input_pdf, output_pdf):
    if convertir_pdf_a_searchable:
        return convertir_pdf_a_searchable(input_pdf, output_pdf)
    raise RuntimeError("función convertir_pdf_a_searchable no disponible")

def generate_json_txt_from_ocr(ocr_pdf_path, out_json_path, out_txt_path, original_pdf_name):
    if not (procesar_paquete and validar_consistencia and generar_reporte):
        raise RuntimeError("Funciones de verificación no disponibles (verificar_prestamos_v3).")
    documentos, num_paginas = procesar_paquete(ocr_pdf_path)
    validaciones, alertas = validar_consistencia(documentos)
    reporte = generar_reporte(ocr_pdf_path, documentos, num_paginas, validaciones, alertas)
    # Ajustar campo archivo para el JSON final
    reporte["archivo"] = original_pdf_name
    # Escribir JSON
    tmp_json = out_json_path + ".tmp"
    with open(tmp_json, "w", encoding="utf-8") as f:
        json.dump(reporte, f, indent=2, ensure_ascii=False)
    os.rename(tmp_json, out_json_path)
    # Generar TXT usando la misma rutina simple que usa el pipeline (mínima)
    tmp_txt = out_txt_path + ".tmp"
    with open(tmp_txt, "w", encoding="utf-8") as f:
        f.write("REPORTE DE VERIFICACIÓN DE PRÉSTAMOS\n")
        f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Archivo: {reporte['archivo']}\n")
        f.write(f"Estado: {reporte['resumen_validacion']}\n")
        f.write(f"Páginas: {reporte['total_paginas']}\n\n")
        f.write("DOCUMENTOS DETECTADOS:\n")
        for tipo, info in reporte['documentos_detectados'].items():
            f.write(f"  {tipo} (Páginas {info.get('paginas')}):\n")
            for campo, valor in info.get('datos', {}).items():
                f.write(f"    {campo}: {valor}\n")
            f.write("\n")
        f.write("VALIDACIONES:\n")
        for val, estado in reporte['validaciones'].items():
            f.write(f"  {val}: {estado}\n")
        if reporte['alertas']:
            f.write("\nALERTAS:\n")
            for alerta in reporte['alertas']:
                f.write(f"  ! {alerta}\n")
        f.write("\n" + "=" * 60 + "\n")
    os.rename(tmp_txt, out_txt_path)

def safe_mkdir(path):
    if not os.path.exists(path):
        os.makedirs(path)

def main(dry_run=False):
    # Verificar dependencias
    if PdfMerger is None:
        print("ERROR: PyPDF2 no disponible. Instala PyPDF2 y vuelve a intentarlo.")
        return 1
    if convertir_pdf_a_searchable is None:
        print("WARNING: convertir_pdf_a_searchable no disponible; OCR fallará si es necesario.")
    if not (procesar_paquete and validar_consistencia and generar_reporte):
        print("WARNING: funciones de verificación no disponibles; generación de JSON/TXT fallará.")

    for p in CARPETAS.values():
        safe_mkdir(p)

    temp_pat = os.path.join(CARPETAS["temp"], "*.pdf")
    files = sorted(glob(temp_pat))
    if not files:
        print("No hay PDFs en Cotizaciones_temp/")
        return 0

    # Agrupar por clave
    groups = {}
    for f in files:
        key = find_group_key(f)
        groups.setdefault(key, []).append(f)

    print(f"Encontrados {len(files)} PDFs en {CARPETAS['temp']}, {len(groups)} grupos detectados.")

    for key, flist in groups.items():
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        combined_name = f"{key}_{timestamp}.pdf"
        combined_path = os.path.join(CARPETAS["entrada"], combined_name)
        print(f"\nProcesando grupo '{key}' ({len(flist)} archivos) -> {combined_name}")

        if dry_run:
            for _f in flist:
                print("  ", _f)
            continue

        # Unir (si solo 1 archivo, lo copia como combinado)
        try:
            if len(flist) == 1:
                shutil.copy2(flist[0], combined_path)
            else:
                merge_pdfs(flist, combined_path)
        except Exception as e:
            print(f"  ERROR al unir archivos del grupo {key}: {e}")
            continue

        # Generar OCR en Cotizaciones_OCR con sufijo _OCR.pdf
        base_combined, _ = os.path.splitext(combined_name)
        ocr_name = f"{base_combined}_OCR.pdf"
        ocr_path = os.path.join(CARPETAS["ocr"], ocr_name)

        try:
            if convertir_pdf_a_searchable:
                print("  Aplicando OCR...")
                ocr_pdf(combined_path, ocr_path)
            else:
                print("  Skipping OCR (no disponible); esperando PDF con texto.")
                shutil.copy2(combined_path, ocr_path)
        except Exception as e:
            print(f"  ERROR en OCR para {combined_name}: {e}")
            continue

        # Generar JSON y TXT en carpetas de resultados
        sanitized_base = re.sub(r'[^\w\-]', '_', base_combined).strip('_')
        out_json = os.path.join(CARPETAS["resultados"], f"{sanitized_base}.json")
        out_txt = os.path.join(CARPETAS["resultados_txt"], f"{sanitized_base}.txt")

        try:
            print("  Generando JSON/TXT desde OCR...")
            generate_json_txt_from_ocr(ocr_path, out_json, out_txt, combined_name)
            print("  OK: JSON y TXT generados.")
        except Exception as e:
            print(f"  ERROR generando JSON/TXT para {combined_name}: {e}")
            # mover combinado a carpeta de error si falla
            try:
                shutil.move(combined_path, os.path.join(CARPETAS["error"], os.path.basename(combined_path)))
            except:
                pass
            continue

        # Limpiar: borrar archivos temporales originales en Cotizaciones_temp
        for _f in flist:
            try:
                os.remove(_f)
            except:
                pass

    print("\nProcesamiento de Cotizaciones_temp completado.")
    return 0

if __name__ == "__main__":
    dry = "--dry-run" in sys.argv or "-n" in sys.argv
    sys.exit(main(dry_run=dry))
'''

    # --- Desplegar helper si no existe ---
    if not os.path.exists(HELPER_NAME):
        try:
            with open(HELPER_NAME, "w", encoding="utf-8") as f:
                f.write(HELPER_CONTENT)
            print(f"\n  [OK] Helper creado: {HELPER_NAME}")
            print("  Uso: python cotizaciones_temp_handler.py")
        except Exception as e:
            print(f"\n  [ERROR] No se pudo escribir el helper: {e}")
    else:
        print(f"\n  [--] Helper ya existe: {HELPER_NAME}")

    # --- Resumen ---
    print("\n" + "="*60)
    print("ESTRUCTURA LISTA")
    print("="*60)
    print(f"""
Estructura de carpetas:

Cotizaciones/           <- PDFs originales (se quedan aqui)
Cotizaciones_OCR/       <- PDFs con OCR aplicado (automatico)
Cotizaciones_Error/     <- PDFs problematicos (automatico)
Resultados_Pendientes/  <- JSONs para el RPA (automatico)
Resultados_TXT/         <- TXTs legibles (automatico)
logs/                   <- Logs de estado (automatico)
Cotizaciones_temp/      <- Coloca aquí PDFs descargados temporalmente

Próximo paso:
    1. Coloca los PDFs (separados) en Cotizaciones_temp/
    2. Ejecuta: python cotizaciones_temp_handler.py
""")

if __name__ == "__main__":
    main()
