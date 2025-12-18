"""
Convierte PDFs escaneados a PDFs buscables/seleccionables usando pypdfium2 + pytesseract.
No requiere Ghostscript. Usa Tesseract directamente para generar PDF con OCR (igual que OCRmyPDF).

Uso:
    python convertir_a_searchable.py                                    # Procesa todos los PDFs del directorio
    python convertir_a_searchable.py archivo.pdf                        # Procesa un archivo especifico
    python convertir_a_searchable.py --input archivo.pdf --output-dir carpeta  # Modo Power Automate
"""
import pypdfium2 as pdfium
import pytesseract
from PIL import Image
from PyPDF2 import PdfReader, PdfWriter, PdfMerger
import glob
import os
import sys
import io
import subprocess
import tempfile
import argparse

# Configurar ruta de Tesseract si no esta en PATH
TESSERACT_CMD = None
TESSERACT_PATHS = [
    r'C:\Users\PR65368\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
]

for path in TESSERACT_PATHS:
    if os.path.exists(path):
        TESSERACT_CMD = path
        pytesseract.pytesseract.tesseract_cmd = path
        break


def crear_pdf_ocr_con_tesseract(pil_image, output_pdf_path):
    """
    Usa Tesseract directamente para crear un PDF con capa de texto OCR.
    Este es el mismo metodo que usa OCRmyPDF internamente.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        # Guardar imagen temporal
        img_path = os.path.join(temp_dir, "page.png")
        pil_image.save(img_path, format='PNG', dpi=(300, 300))
        
        # Ejecutar Tesseract para generar PDF
        output_base = os.path.join(temp_dir, "output")
        
        cmd = [
            TESSERACT_CMD,
            img_path,
            output_base,
            '-l', 'spa+eng',
            'pdf'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            raise Exception(f"Tesseract error: {result.stderr}")
        
        # Leer el PDF generado
        generated_pdf = output_base + ".pdf"
        with open(generated_pdf, 'rb') as f:
            return f.read()


def convertir_pdf_a_searchable(pdf_entrada, pdf_salida=None, forzar_ocr=False):
    """
    Convierte un PDF escaneado a un PDF con texto seleccionable.
    Usa Tesseract directamente para generar PDFs con OCR (igual que OCRmyPDF).
    """
    if pdf_salida is None:
        base, ext = os.path.splitext(pdf_entrada)
        pdf_salida = f"{base}_OCR{ext}"
    
    print(f"Procesando: {pdf_entrada}")
    print(f"  Salida: {pdf_salida}")
    
    try:
        # Abrir PDF con pypdfium2
        pdf = pdfium.PdfDocument(pdf_entrada)
        num_paginas = len(pdf)
        
        # Usar directorio temporal para paginas
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_paginas = []
            
            for i in range(num_paginas):
                print(f"  Procesando pagina {i + 1}/{num_paginas}...", end=" ", flush=True)
                
                # Renderizar pagina como imagen (300 DPI para buen OCR)
                page = pdf[i]
                scale = 300 / 72  # 300 DPI
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                
                # Generar PDF con OCR usando Tesseract
                pdf_bytes = crear_pdf_ocr_con_tesseract(pil_image, None)
                
                # Guardar pagina temporal
                pagina_path = os.path.join(temp_dir, f"pagina_{i}.pdf")
                with open(pagina_path, 'wb') as f:
                    f.write(pdf_bytes)
                pdf_paginas.append(pagina_path)
                
                print("[OK]")
            
            pdf.close()
            
            # Combinar todas las paginas
            merger = PdfMerger()
            for pagina_path in pdf_paginas:
                merger.append(pagina_path)
            
            # Guardar PDF final
            with open(pdf_salida, 'wb') as output_file:
                merger.write(output_file)
            merger.close()
        
        print(f"  [OK] Conversion exitosa!")
        size_original = os.path.getsize(pdf_entrada) / 1024 / 1024
        size_nuevo = os.path.getsize(pdf_salida) / 1024 / 1024
        print(f"  Tamano: {size_original:.2f} MB -> {size_nuevo:.2f} MB")
        return pdf_salida
        
    except Exception as e:
        print(f"\n  [X] Error: {e}")
        import traceback
        traceback.print_exc()
        return None


def verificar_dependencias():
    """Verifica que todas las dependencias esten instaladas."""
    print("Verificando dependencias...")
    todas_ok = True
    
    # Verificar Tesseract
    if TESSERACT_CMD and os.path.exists(TESSERACT_CMD):
        try:
            version = pytesseract.get_tesseract_version()
            print(f"  [OK] Tesseract OCR: v{version}")
        except:
            print(f"  [OK] Tesseract OCR: {TESSERACT_CMD}")
    else:
        print(f"  [X] Tesseract OCR: No encontrado")
        todas_ok = False
    
    # Verificar pypdfium2
    try:
        import pypdfium2
        print(f"  [OK] pypdfium2: instalado")
    except ImportError:
        print(f"  [X] pypdfium2: No instalado (pip install pypdfium2)")
        todas_ok = False
    
    # Verificar Pillow
    try:
        from PIL import Image
        print(f"  [OK] Pillow: instalado")
    except ImportError:
        print(f"  [X] Pillow: No instalado (pip install Pillow)")
        todas_ok = False
    
    # Verificar PyPDF2
    try:
        from PyPDF2 import PdfReader
        print(f"  [OK] PyPDF2: instalado")
    except ImportError:
        print(f"  [X] PyPDF2: No instalado (pip install PyPDF2)")
        todas_ok = False
    
    print()
    return todas_ok


if __name__ == "__main__":
    # Verificar dependencias primero
    if not verificar_dependencias():
        print("[!] Algunas dependencias no estan instaladas.")
        print("  El script intentara continuar de todos modos.\n")
    
    # Configurar argumentos de línea de comandos
    parser = argparse.ArgumentParser(
        description='Convierte PDFs escaneados a PDFs buscables con OCR.',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--input', '-i', type=str, help='Archivo PDF de entrada')
    parser.add_argument('--output-dir', '-o', type=str, help='Directorio de salida para el PDF con OCR')
    parser.add_argument('archivos', nargs='*', help='Archivos PDF a procesar (modo legacy)')
    
    args = parser.parse_args()
    
    # Modo con argumentos --input (para Power Automate)
    if args.input:
        if not os.path.exists(args.input):
            print(f"[X] Archivo no encontrado: {args.input}")
            sys.exit(1)
        
        # Determinar archivo de salida
        base_name = os.path.splitext(os.path.basename(args.input))[0]
        if args.output_dir:
            # Crear directorio si no existe
            os.makedirs(args.output_dir, exist_ok=True)
            pdf_salida = os.path.join(args.output_dir, f"{base_name}_OCR.pdf")
        else:
            pdf_salida = None  # Usará el directorio del archivo original
        
        resultado = convertir_pdf_a_searchable(args.input, pdf_salida)
        sys.exit(0 if resultado else 1)
    
    # Modo legacy (archivos como argumentos posicionales o buscar en directorio)
    if args.archivos:
        archivos = args.archivos
    else:
        # Buscar todos los PDFs que NO sean ya _OCR.pdf
        archivos = [f for f in glob.glob("*.pdf") if not f.endswith("_OCR.pdf")]
    
    if not archivos:
        print("No se encontraron archivos PDF para procesar.")
        print("Uso: python convertir_a_searchable.py [archivo1.pdf archivo2.pdf ...]")
        print("  o: python convertir_a_searchable.py --input archivo.pdf --output-dir carpeta")
        sys.exit(0)
    
    print(f"Encontrados {len(archivos)} PDFs para convertir.\n")
    print("=" * 60)
    
    exitosos = 0
    fallidos = 0
    
    for archivo in archivos:
        if not os.path.exists(archivo):
            print(f"[!] Archivo no encontrado: {archivo}")
            fallidos += 1
            continue
        
        # Determinar salida si hay output_dir
        if args.output_dir:
            os.makedirs(args.output_dir, exist_ok=True)
            base_name = os.path.splitext(os.path.basename(archivo))[0]
            pdf_salida = os.path.join(args.output_dir, f"{base_name}_OCR.pdf")
        else:
            pdf_salida = None
            
        resultado = convertir_pdf_a_searchable(archivo, pdf_salida)
        if resultado:
            exitosos += 1
        else:
            fallidos += 1
        print()
    
    print("=" * 60)
    print(f"Proceso completado.")
    print(f"  [OK] Exitosos: {exitosos}")
    if fallidos > 0:
        print(f"  [X] Fallidos: {fallidos}")
        sys.exit(1)
    print("\nLos archivos _OCR.pdf ahora son seleccionables y buscables.")
    print("Puedes abrirlos en cualquier visor de PDF y copiar/pegar texto.")
    sys.exit(0)
