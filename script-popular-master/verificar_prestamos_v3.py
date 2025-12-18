"""
Verificador de Paquetes de Préstamos - v3.0
Detecta tipos de documento por contenido y extrae campos usando etiquetas genéricas.
Incluye detección de firmas manuscritas con OpenCV.

Uso:
    python verificar_prestamos_v3.py                                    # Procesa todos los PDFs del directorio
    python verificar_prestamos_v3.py --input archivo.pdf --output-dir carpeta  # Modo Power Automate
"""

import fitz  # PyMuPDF
import re
import json
import glob
import os
import sys
import argparse
import traceback
import shutil
import time
import subprocess
import tempfile
from datetime import datetime
from glob import glob

# Intentar importar dependencias de OCR
try:
    import pypdfium2 as pdfium
    from PIL import Image
    from PyPDF2 import PdfReader, PdfWriter, PdfMerger
    import pytesseract
    OCR_DISPONIBLE = True
except ImportError:
    OCR_DISPONIBLE = False

# Intentar importar OpenCV para detección de firmas manuscritas
try:
    import cv2
    import numpy as np
    OPENCV_DISPONIBLE = True
except ImportError:
    OPENCV_DISPONIBLE = False

# =============================================================================
# FUNCIONES AUXILIARES REUSABLES (exportadas)
# =============================================================================
def merge_pdfs(file_list, output_path):
    """
    Une una lista de archivos PDF en `output_path`.
    Función reutilizable exportada para que otros scripts del repo la usen.

    Requiere `PyPDF2.PdfMerger` disponible; lanza RuntimeError si no lo está.
    """
    try:
        from PyPDF2 import PdfMerger
    except Exception:
        raise RuntimeError("PyPDF2 no disponible: instala PyPDF2 para poder unir PDFs")

    merger = PdfMerger()
    for p in file_list:
        merger.append(p)
    with open(output_path, "wb") as fout:
        merger.write(fout)
    merger.close()

# =============================================================================
# CONFIGURACIÓN DEL PIPELINE
# =============================================================================

# Carpetas del pipeline
CARPETAS = {
    "entrada": "Cotizaciones",
    "ocr": "Cotizaciones_OCR",
    "error": "Cotizaciones_Error",
    "resultados": "Resultados_Pendientes",
    "resultados_txt": "Resultados_TXT",
    "logs": "logs",
}

# Archivo de log
LOG_FILE = os.path.join(CARPETAS["logs"], "estado_procesamiento.csv")

# Límite de errores antes de mover a Cotizaciones_Error
MAX_ERRORES = 3

# Tiempo máximo para archivos .tmp huérfanos (en segundos)
MAX_EDAD_TMP = 3600  # 1 hora

# =============================================================================
# CONFIGURACIÓN DE TESSERACT OCR
# =============================================================================

TESSERACT_CMD = None
TESSERACT_PATHS = [
    r'C:\Users\PR65368\AppData\Local\Programs\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
]

# Buscar Tesseract en las rutas conocidas
for path in TESSERACT_PATHS:
    if os.path.exists(path):
        TESSERACT_CMD = path
        if OCR_DISPONIBLE:
            pytesseract.pytesseract.tesseract_cmd = path
        break

# =============================================================================
# CONFIGURACIÓN DE TIPOS DE DOCUMENTO
# =============================================================================

# IMPORTANTE: El orden de los tipos importa. Los más específicos primero.
# La función detectar_tipo_documento evalúa en este orden.

TIPOS_DOCUMENTO = {
    # 1. AUTORIZACION_SEGUROS - Muy específico, evaluar primero
    "AUTORIZACION_SEGUROS": {
        "identificadores": [
            "Autorización para referir los seguros",
            "Autorización para referir",
        ],
        "identificadores_negativos": [],
        "campos": {
            "nombre_solicitante": [
                r"Nombre\s+del\s+Solicitante[:\s]*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?=\n|Nombre\s+del\s+Co|$)",
            ],
            "num_solicitud": [
                r"N[uú]mero\s+de\s+Solicitud[:\s]*(\d{10})",
            ],
            "linea_rechazo": "VERIFICAR_BLANCO",  # Lógica especial
        },
        "requiere_firma": True,
    },
    
    # 2. DIVULGACIONES_TITULO - Específico
    "DIVULGACIONES_TITULO": {
        "identificadores": [
            "Divulgaciones Seguro de Título",
            "Divulgaciones Seguro de Titulo",
        ],
        "identificadores_negativos": [],
        "campos": {
            "num_solicitud": [
                r"N[uú]mero\s+de\s+solicitud[:\s]*(\d{10})",
                r"N[uú]mero\s+de\s+pr[eé]stamo[:\s]*(\d{10})",
            ],
        },
        "requiere_firma": True,
    },
    
    # 3. DIVULGACIONES_PRODUCTOS - Específico
    "DIVULGACIONES_PRODUCTOS": {
        "identificadores": [
            "Divulgaciones relacionadas a los productos de seguro",
        ],
        "identificadores_negativos": [],
        "campos": {
            "num_solicitud": [
                r"N[uú]mero\s+de\s+pr[eé]stamo[:\s]*(\d{10})",
                r"N[uú]mero\s+de\s+solicitud[:\s]*(\d{10})",
            ],
        },
        "requiere_firma": True,
    },
    
    # 4. CARTA_SOLICITUD - Tiene identificadores comunes, necesita negativos
    "CARTA_SOLICITUD": {
        "identificadores": [
            "Solicitud de Cotización Póliza de Título",
            "Solicitud de Cotización",
            "popularMortgage.com",
        ],
        "identificadores_negativos": [
            "Autorización para referir",
            "Divulgaciones",
        ],
        "campos": {
            "nombre_solicitante": [
                r"Nombre\s+del\s+Solicitante[:\s]*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?=\n|Nombre\s+del\s+Co|$)",
            ],
            "direccion_postal": [
                r"Direcci[oó]n\s+Postal[:\s]*([^\n]+(?:\n[^\n]*(?:PR|00\d{3}))?)",
            ],
            "ssn": [
                r"N[uú]mero\s+de\s+Seguro\s+Social\s+del\s+Solicitante[:\s]*(\d{3}-\d{2}-\d{4})",
                r"(\d{3}-\d{2}-\d{4})",
            ],
            "email": [
                r"Correo\s+Electr[oó]nico[:\s]*([^\n]+)",
            ],
            "cantidad_hipoteca": [
                r"Cantidad\s+de\s+la\s+Hipoteca[:\s]*\$?\s*([\d,]+\.?\d*)",
                r"Hipoteca[:\s]*\$?\s*([\d,]+\.?\d*)",
            ],
            "precio_venta": [
                r"Precio\s+de\s+Venta[:\s]*\$?\s*([\d,]+\.?\d*)",
            ],
            "tipo_prestamo": [
                r"Tipo\s+de\s+Pr[eé]stamo[:\s]*([^\n]+)",
            ],
            "fecha_estimada_cierre": [
                r"Fecha\s+estimada\s+de\s+cierre[:\s]*(\d{1,2}/\d{1,2}/\d{4})",
            ],
        },
        "requiere_firma": False,
    },
    
    # 5. ESTUDIO_TITULO - Documento principal del estudio
    "ESTUDIO_TITULO": {
        "identificadores": [
            "ESTUDIO",
            "Capital Title",
            "CAPITAL TITLE",
        ],
        "identificadores_negativos": [
            "Divulgaciones Seguro de Título",
            "popularMortgage.com",
            "Continuación",  # Las páginas de continuación se clasifican aparte
        ],
        "campos": {
            "finca": [
                r"FINCA\s*[:\s]*(?:N[uú]mero\s*)?([\d,]+)",
                r"Finca\s+n[uú]mero\s+([\d,]+)",
            ],
            "tipo_propiedad": "DETECTAR_TIPO",  # Lógica especial
            "fecha_documento": "ULTIMA_FECHA_ESTUDIO",  # Lógica especial - busca en continuaciones
        },
        "requiere_firma": False,
        "incluir_continuaciones": True,
    },
    
    # 6. ESTUDIO_TITULO_CONTINUACION - Páginas de continuación (al final, menos prioritario)
    "ESTUDIO_TITULO_CONTINUACION": {
        "identificadores": [
            "Continuación",
            "Continuacion",
        ],
        "identificadores_negativos": [
            "Autorización",  # Si tiene autorización, no es continuación
            "Divulgaciones",  # Si tiene divulgaciones, no es continuación
        ],
        "campos": {},  # No extraemos campos, solo se usa para la fecha
        "requiere_firma": False,
        "es_continuacion_de": "ESTUDIO_TITULO",
    },
}

# =============================================================================
# FUNCIONES DE OCR (copiadas de convertir_a_searchable.py)
# =============================================================================

def crear_pdf_ocr_con_tesseract(pil_image, output_pdf_path):
    """
    Usa Tesseract directamente para crear un PDF con capa de texto OCR.
    Este es el mismo método que usa OCRmyPDF internamente.
    """
    if not OCR_DISPONIBLE or not TESSERACT_CMD:
        raise Exception("OCR no disponible: faltan dependencias o Tesseract no encontrado")
    
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
    if not OCR_DISPONIBLE:
        raise Exception("OCR no disponible: faltan dependencias (pypdfium2, pytesseract, PIL, PyPDF2)")
    
    if not TESSERACT_CMD:
        raise Exception("Tesseract OCR no encontrado en las rutas conocidas")
    
    if pdf_salida is None:
        base, ext = os.path.splitext(pdf_entrada)
        pdf_salida = f"{base}_OCR{ext}"
    
    print(f"Procesando: {pdf_entrada}")
    print(f"  Salida: {pdf_salida}")
    
    try:
        # Abrir PDF con pypdfium2
        pdf = pdfium.PdfDocument(pdf_entrada)
        num_paginas = len(pdf)
        
        # Usar directorio temporal para páginas
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_paginas = []
            
            for i in range(num_paginas):
                print(f"  Procesando página {i + 1}/{num_paginas}...", end=" ", flush=True)
                
                # Renderizar página como imagen (300 DPI para buen OCR)
                page = pdf[i]
                scale = 300 / 72  # 300 DPI
                bitmap = page.render(scale=scale)
                pil_image = bitmap.to_pil()
                
                # Generar PDF con OCR usando Tesseract
                pdf_bytes = crear_pdf_ocr_con_tesseract(pil_image, None)
                
                # Guardar página temporal
                pagina_path = os.path.join(temp_dir, f"pagina_{i}.pdf")
                with open(pagina_path, 'wb') as f:
                    f.write(pdf_bytes)
                pdf_paginas.append(pagina_path)
                
                print("[OK]")
            
            pdf.close()
            
            # Combinar todas las páginas
            merger = PdfMerger()
            for pagina_path in pdf_paginas:
                merger.append(pagina_path)
            
            # Guardar PDF final
            with open(pdf_salida, 'wb') as output_file:
                merger.write(output_file)
            merger.close()
        
        print(f"  [OK] Conversión exitosa!")
        size_original = os.path.getsize(pdf_entrada) / 1024 / 1024
        size_nuevo = os.path.getsize(pdf_salida) / 1024 / 1024
        print(f"  Tamaño: {size_original:.2f} MB -> {size_nuevo:.2f} MB")
        return pdf_salida
        
    except Exception as e:
        print(f"\n  [X] Error: {e}")
        import traceback
        traceback.print_exc()
        return None

# =============================================================================
# FUNCIONES DE UTILIDAD
# =============================================================================

def limpiar(texto):
    """Limpia texto de caracteres extra."""
    if not texto:
        return ""
    texto = re.sub(r'\s+', ' ', texto)
    texto = texto.strip()
    return texto


def formatear_precio(valor):
    """Formatea un valor numérico como precio."""
    if not valor:
        return None
    valor_limpio = valor.replace(',', '').replace(' ', '')
    try:
        num = float(valor_limpio)
        if num > 1000:  # Solo si es un número razonable
            return f"${num:,.2f}"
    except:
        pass
    return None


def limpiar_email(contenido):
    """Limpia y extrae email del contenido."""
    if not contenido:
        return None
    # Limpiar caracteres de OCR problemáticos
    contenido = contenido.replace('|', '').strip()
    contenido = re.sub(r'\s+', '', contenido)
    # Extraer email
    match = re.search(r'([\w\.\-]+@[\w\.\-]+\.[a-z]{2,})', contenido, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    return contenido.lower() if '@' in contenido else None


# =============================================================================
# FUNCIÓN: DETECTAR TIPO DE DOCUMENTO
# =============================================================================

def detectar_tipo_documento(texto):
    """
    Identifica el tipo de documento basándose en su contenido.
    Retorna el tipo de documento o None si no se reconoce.
    """
    texto_upper = texto.upper()
    
    for tipo, config in TIPOS_DOCUMENTO.items():
        # Verificar identificadores negativos primero
        negativos = config.get("identificadores_negativos", [])
        tiene_negativo = any(neg.upper() in texto_upper for neg in negativos)
        
        # Verificar identificadores positivos
        identificadores = config["identificadores"]
        tiene_positivo = any(ident.upper() in texto_upper for ident in identificadores)
        
        if tiene_positivo and not tiene_negativo:
            return tipo
    
    return None


# =============================================================================
# FUNCIÓN: EXTRAER CAMPO GENÉRICO
# =============================================================================

def extraer_campo(texto, patrones):
    """
    Extrae un valor del texto usando una lista de patrones regex.
    Intenta cada patrón en orden hasta encontrar una coincidencia.
    """
    if isinstance(patrones, str):
        # Es una lógica especial, no un patrón
        return None
    
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
        if match:
            valor = limpiar(match.group(1))
            if valor:
                return valor
    
    return None


# =============================================================================
# FUNCIONES ESPECIALES DE EXTRACCIÓN
# =============================================================================

def detectar_tipo_propiedad(texto):
    """Detecta si es CASA o APARTAMENTO basándose en el contenido."""
    texto_upper = texto.upper()
    
    indicadores_apartamento = [
        "PROPIEDAD HORIZONTAL",
        "APARTAMENTO",
        "CONDOMINIO",
        "APT",
    ]
    
    indicadores_casa = [
        "SOLAR",
        "CASA",
        "TERRENO",
        "URBANIZACIÓN",
        "URBANA",
    ]
    
    for indicador in indicadores_apartamento:
        if indicador in texto_upper:
            return "APARTAMENTO"
    
    for indicador in indicadores_casa:
        if indicador in texto_upper:
            return "CASA"
    
    return "INDETERMINADO"


def extraer_ultima_fecha(texto):
    """
    Extrae la última fecha en formato "DD de MES de YYYY".
    Esta es típicamente la fecha del documento (después de POR:).
    """
    patron = r'(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4})'
    fechas = re.findall(patron, texto, re.IGNORECASE)
    
    if fechas:
        return fechas[-1]  # Última fecha encontrada
    
    # Fallback: fecha numérica
    patron_num = r'(\d{1,2}/\d{1,2}/\d{4})'
    fechas_num = re.findall(patron_num, texto)
    if fechas_num:
        return fechas_num[-1]
    
    return None


# Variable global para almacenar texto de continuaciones (se usa en procesar_paquete)
_texto_continuaciones_estudio = ""


def extraer_ultima_fecha_estudio(texto):
    """
    Extrae la última fecha del estudio de título.
    Busca también en las páginas de continuación.
    """
    global _texto_continuaciones_estudio
    
    # Combinar texto del estudio principal con continuaciones
    texto_completo = texto + "\n" + _texto_continuaciones_estudio
    
    return extraer_ultima_fecha(texto_completo)


def verificar_linea_rechazo(texto):
    """
    Verifica si la línea de rechazo de seguros está en blanco.
    Retorna el estado de la verificación.
    """
    patrones = [
        r'que\s+no\s+desea\s+que\s+Popular[^:]*gestione[:\s]*([^\n]{0,100})',
        r'favor\s+indicar\s+el\s+seguro\s+que\s+no\s+desea[^:]*:[:\s]*([^\n]{0,100})',
        r'Insurance\s+gestione[:\s]*([^\n]{0,100})',
    ]
    
    texto_formulario = [
        "firma del solicitante", "firma del co-solicitante", "firma", 
        "solicitante", "co-solicitante", "fecha", "mortg", "rev"
    ]
    
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            contenido = (match.group(1) or "").strip()
            contenido_limpio = re.sub(r'[_\-\.\s\n:]+', '', contenido).lower()
            
            if not contenido_limpio or len(contenido_limpio) < 3:
                return "CORRECTO (Está en blanco)"
            
            es_formulario = any(txt in contenido.lower() for txt in texto_formulario)
            if es_formulario:
                return "CORRECTO (Está en blanco)"
            else:
                return f"ALERTA: Contiene texto ('{contenido[:50]}')"
    
    return "NO LOCALIZADO"


def detectar_firma_manuscrita_en_area(page, area_texto="Firma del Solicitante"):
    """
    Detecta si hay una firma manuscrita en el área cercana a un texto específico.
    Usa OpenCV para analizar si hay trazos/líneas en esa área.
    
    Returns:
        (tiene_firma, confianza, descripcion)
    """
    if not OPENCV_DISPONIBLE:
        return None, 0, "OpenCV no disponible"
    
    try:
        # Buscar el área donde dice "Firma del Solicitante"
        text_instances = page.search_for(area_texto)
        
        if not text_instances:
            return None, 0, "Área de firma no encontrada"
        
        # Tomar la primera instancia
        rect = text_instances[0]
        
        # Expandir el área hacia arriba (donde está la firma)
        # La firma generalmente está ARRIBA del texto "Firma del Solicitante"
        firma_rect = fitz.Rect(
            rect.x0 - 50,           # Un poco a la izquierda
            rect.y0 - 80,           # Bastante arriba (donde está la firma)
            rect.x1 + 100,          # A la derecha
            rect.y0 - 5             # Justo arriba del texto
        )
        
        # Asegurar que el rectángulo está dentro de la página
        page_rect = page.rect
        firma_rect = firma_rect & page_rect
        
        if firma_rect.is_empty:
            return None, 0, "Área de firma fuera de página"
        
        # Renderizar solo esa área como imagen
        mat = fitz.Matrix(3, 3)  # 3x zoom para mejor detección
        clip = firma_rect
        pix = page.get_pixmap(matrix=mat, clip=clip)
        
        # Convertir a formato OpenCV
        img_data = pix.tobytes("png")
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return None, 0, "Error al procesar imagen"
        
        # Convertir a escala de grises
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Aplicar umbral para detectar tinta (líneas oscuras)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        # Contar píxeles de tinta
        pixeles_tinta = cv2.countNonZero(thresh)
        total_pixeles = thresh.shape[0] * thresh.shape[1]
        porcentaje_tinta = (pixeles_tinta / total_pixeles) * 100
        
        # Detectar contornos (líneas de firma)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Filtrar contornos muy pequeños (ruido)
        contornos_significativos = [c for c in contours if cv2.contourArea(c) > 20]
        num_contornos = len(contornos_significativos)
        
        # Analizar resultados
        if porcentaje_tinta > 0.5 and num_contornos >= 3:
            confianza = min(95, 50 + (porcentaje_tinta * 10) + (num_contornos * 2))
            return True, confianza, f"Firma manuscrita detectada ({num_contornos} trazos, {porcentaje_tinta:.1f}% tinta)"
        elif porcentaje_tinta > 0.2 or num_contornos >= 2:
            confianza = 30 + (porcentaje_tinta * 5) + (num_contornos * 5)
            return True, confianza, f"Posible firma ({num_contornos} trazos)"
        else:
            return False, 10, "Area de firma vacia"
            
    except Exception as e:
        return None, 0, f"Error: {str(e)}"


def detectar_firma_manuscrita_pagina_completa(page):
    """
    Busca firmas manuscritas en toda la página (cuando no hay texto indicador).
    Analiza la parte inferior de la página donde típicamente van las firmas.
    
    Returns:
        (tiene_firma, confianza, descripcion)
    """
    if not OPENCV_DISPONIBLE:
        return None, 0, "OpenCV no disponible"
    
    try:
        # Analizar el tercio inferior de la página
        page_rect = page.rect
        firma_rect = fitz.Rect(
            page_rect.x0,
            page_rect.y1 * 0.6,  # Desde el 60% hacia abajo
            page_rect.x1,
            page_rect.y1
        )
        
        mat = fitz.Matrix(2, 2)
        pix = page.get_pixmap(matrix=mat, clip=firma_rect)
        
        img_data = pix.tobytes("png")
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return None, 0, "Error al procesar imagen"
        
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        # Detectar líneas horizontales (líneas de firma)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
        lineas = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
        num_lineas = cv2.countNonZero(lineas) > 100
        
        # Detectar trazos sobre las líneas
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contornos_firma = [c for c in contours if 50 < cv2.contourArea(c) < 5000]
        
        if len(contornos_firma) >= 5:
            return True, 60, f"Posible firma manuscrita ({len(contornos_firma)} trazos en area inferior)"
        
        return False, 10, "No se detectaron firmas manuscritas"
        
    except Exception as e:
        return None, 0, f"Error: {str(e)}"


# =============================================================================
# PALABRAS CLAVE UNIVERSALES PARA DETECCIÓN DE FIRMAS
# =============================================================================

# Palabras que indican áreas de firma (aplicable a cualquier documento)
PALABRAS_AREA_FIRMA = [
    "Firma del Solicitante",
    "Firma del Cliente", 
    "Firma del Deudor",
    "Firma del Comprador",
    "Firma del Vendedor",
    "Firma del Propietario",
    "Firma del Representante",
    "Firma",
    "Signature",
    "Signed",
    "Firmado por",
    "Firmado",
]

# Palabras que indican certificación (antes de firma)
PALABRAS_CERTIFICACION = [
    "Certifico",
    "Certify",
    "Declaro",
    "Declare",
    "Acepto",
    "Accept",
    "Autorizo",
    "Authorize",
    "Confirmo",
    "Confirm",
]


def detectar_firma(texto, page=None):
    """
    Detecta si hay una firma en el documento (UNIVERSAL).
    Funciona con cualquier tipo de documento.
    
    Retorna (tiene_firma, tipo_firma, detalle_firma).
    
    Args:
        texto: Texto extraído de la página
        page: Objeto page de PyMuPDF (opcional, para detección visual)
    
    Tipos de firma detectados:
        - Firma Electronica (Timestamp): NOMBRE + fecha + hora + timezone
        - Firma Electronica: Nombre después de certificación
        - Firma con Marca X: Patrón X antes de "Firma"
        - Firma Manuscrita: Trazos detectados con OpenCV
        - Firma de Texto: Nombre escrito en área de firma
    """
    # Normalizar texto (quitar saltos de línea extras para mejor detección)
    texto_norm = re.sub(r'\s+', ' ', texto)
    
    # =========================================================================
    # PATRÓN 1: Firma electrónica con timestamp completo
    # Ejemplo: "JUAN PEREZ GARCIA 10/10/2025 7:29 AM PDT"
    # =========================================================================
    patron_timestamp = r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]{3,40}?)\s*(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s*(?:PDT|PST|EST|CST|MST|UTC)?)?)'
    match_ts = re.search(patron_timestamp, texto_norm, re.IGNORECASE)
    if match_ts:
        nombre = match_ts.group(1).strip()
        # Validar que sea un nombre real (no texto del documento)
        palabras_excluir = ['DOCUMENTO', 'SEGURO', 'TITULO', 'BANCO', 'NUMERO', 'FECHA', 'PAGINA']
        if len(nombre) > 5 and not any(p in nombre.upper() for p in palabras_excluir):
            return True, "Firma Electronica (Timestamp)", f"{nombre} - {match_ts.group(2)} {match_ts.group(3)}"
    
    # =========================================================================
    # PATRÓN 2: Solo timestamp cerca de palabras de firma/certificación
    # =========================================================================
    palabras_contexto = '|'.join(PALABRAS_AREA_FIRMA + PALABRAS_CERTIFICACION)
    if re.search(rf'({palabras_contexto})', texto_norm, re.IGNORECASE):
        patron_ts_solo = r'(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s*(?:PDT|PST|EST|CST|MST|UTC)?)?)'
        match_ts_solo = re.search(patron_ts_solo, texto_norm)
        if match_ts_solo:
            return True, "Firma Electronica (Timestamp)", match_ts_solo.group(1)
    
    # =========================================================================
    # PATRÓN 3: Nombre después de palabras de certificación
    # Ejemplo: "Certifico haber leído... JUAN PEREZ"
    # =========================================================================
    for palabra in PALABRAS_CERTIFICACION:
        patron_cert = rf'{palabra}[^A-Z]{{0,100}}([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]{{5,40}}?)(?:\d{{1,2}}/|\n|Firma|$)'
        match_cert = re.search(patron_cert, texto_norm, re.IGNORECASE)
        if match_cert:
            nombre = match_cert.group(1).strip()
            palabras_excluir = ['DOCUMENTO', 'SEGURO', 'TITULO', 'BANCO', 'DIVULGACIONES', 'PRESENTADAS']
            if len(nombre) > 5 and not any(p in nombre.upper() for p in palabras_excluir):
                return True, "Firma Electronica", nombre
    
    # =========================================================================
    # PATRÓN 4: Marca X como firma
    # =========================================================================
    if re.search(r'[xX]{1,3}\s*(?:Firma|Signature|___|---)', texto):
        return True, "Firma con Marca X", "Marca X detectada"
    if re.search(r'(?:Firma|Signature)\s*[:\s]*[xX]{1,3}', texto):
        return True, "Firma con Marca X", "Marca X detectada"
    
    # =========================================================================
    # PATRÓN 5: Detección visual de firma manuscrita con OpenCV
    # =========================================================================
    if page is not None and OPENCV_DISPONIBLE:
        # Intentar detectar firma en áreas conocidas
        for palabra in PALABRAS_AREA_FIRMA:
            if palabra.lower() in texto.lower():
                tiene_firma_visual, confianza, detalle = detectar_firma_manuscrita_en_area(page, palabra)
                if tiene_firma_visual and confianza > 40:
                    return True, "Firma Manuscrita", detalle
                elif tiene_firma_visual and confianza > 25:
                    return True, "Posible Firma Manuscrita", detalle
        
        # Buscar en toda la página (último recurso)
        tiene_firma_visual, confianza, detalle = detectar_firma_manuscrita_pagina_completa(page)
        if tiene_firma_visual and confianza > 50:
            return True, "Posible Firma Manuscrita", detalle
    
    # =========================================================================
    # PATRÓN 6: Área de firma detectada pero sin contenido verificable
    # =========================================================================
    for palabra in PALABRAS_AREA_FIRMA:
        if palabra.lower() in texto.lower():
            if page is not None and OPENCV_DISPONIBLE:
                return False, "Area de firma vacia", f"No se detecto contenido cerca de '{palabra}'"
            return None, "Area de firma detectada", f"Encontrado: '{palabra}' (instale OpenCV para verificacion visual)"
    
    return False, "No encontrada", None


# =============================================================================
# FUNCIÓN: EXTRAER CAMPOS POR TIPO DE DOCUMENTO
# =============================================================================

def extraer_campos_por_tipo(texto, tipo_documento, page=None):
    """
    Extrae todos los campos configurados para un tipo de documento.
    
    Args:
        texto: Texto extraído del documento
        tipo_documento: Tipo de documento detectado
        page: Objeto page de PyMuPDF (opcional, para detección visual de firmas)
    """
    if tipo_documento not in TIPOS_DOCUMENTO:
        return {}
    
    config = TIPOS_DOCUMENTO[tipo_documento]
    campos_config = config["campos"]
    datos = {}
    
    for campo, patrones in campos_config.items():
        # Manejar lógicas especiales
        if patrones == "DETECTAR_TIPO":
            datos[campo] = detectar_tipo_propiedad(texto)
        elif patrones == "ULTIMA_FECHA":
            datos[campo] = extraer_ultima_fecha(texto)
        elif patrones == "ULTIMA_FECHA_ESTUDIO":
            datos[campo] = extraer_ultima_fecha_estudio(texto)
        elif patrones == "VERIFICAR_BLANCO":
            datos[campo] = verificar_linea_rechazo(texto)
        else:
            # Extracción normal con patrones
            valor = extraer_campo(texto, patrones)
            
            # Post-procesamiento según el campo
            if campo == "email":
                valor = limpiar_email(valor)
            elif campo in ["cantidad_hipoteca", "precio_venta"]:
                valor = formatear_precio(valor)
            elif campo == "direccion_postal" and valor:
                # Limpiar dirección y unir líneas
                valor = re.sub(r'\s+', ' ', valor).strip()
            elif campo == "finca" and valor:
                # Limpiar comas extra al final
                valor = valor.rstrip(',').strip()
            
            datos[campo] = valor
    
    # Detectar firma si es requerida
    if config.get("requiere_firma", False):
        tiene_firma, tipo_firma, detalle = detectar_firma(texto, page=page)
        datos["firma"] = {
            "presente": tiene_firma,
            "tipo": tipo_firma,
            "detalle": detalle
        }
    
    return datos


# =============================================================================
# FUNCIÓN: PROCESAR PAQUETE DE DOCUMENTOS
# =============================================================================

def procesar_paquete(pdf_path):
    """
    Procesa un paquete de documentos PDF.
    Detecta el tipo de cada página y extrae los campos correspondientes.
    """
    global _texto_continuaciones_estudio
    
    doc = fitz.open(pdf_path)
    num_paginas = len(doc)
    
    # Estructura para almacenar resultados
    documentos_encontrados = {}
    paginas_por_tipo = {}
    
    print(f"  Analizando {num_paginas} páginas...")
    
    # Resetear texto de continuaciones
    _texto_continuaciones_estudio = ""
    
    # Primera pasada: detectar tipo de cada página
    for i in range(num_paginas):
        texto = doc[i].get_text()
        tipo = detectar_tipo_documento(texto)
        
        if tipo:
            # Si es una continuación del estudio, guardar el texto pero no clasificar
            if tipo == "ESTUDIO_TITULO_CONTINUACION":
                _texto_continuaciones_estudio += "\n" + texto
                print(f"    Página {i+1}: (continuación de estudio)")
                continue
            
            if tipo not in paginas_por_tipo:
                paginas_por_tipo[tipo] = []
            paginas_por_tipo[tipo].append(i)
            print(f"    Página {i+1}: {tipo}")
        else:
            print(f"    Página {i+1}: (no clasificada)")
    
    # Segunda pasada: extraer campos por tipo de documento
    for tipo, paginas in paginas_por_tipo.items():
        # Combinar texto de todas las páginas del mismo tipo
        texto_combinado = "\n".join([doc[p].get_text() for p in paginas])
        
        # Usar la primera página del tipo para detección visual de firma
        primera_pagina = doc[paginas[0]] if paginas else None
        
        # Extraer campos
        datos = extraer_campos_por_tipo(texto_combinado, tipo, page=primera_pagina)
        
        documentos_encontrados[tipo] = {
            "paginas": [p + 1 for p in paginas],  # 1-indexed para el reporte
            "datos": datos
        }
    
    doc.close()
    
    return documentos_encontrados, num_paginas


# =============================================================================
# FUNCIÓN: VALIDACIONES CRUZADAS
# =============================================================================

def validar_consistencia(documentos):
    """
    Realiza validaciones cruzadas entre los diferentes documentos del paquete.
    """
    validaciones = {
        "nombre_consistente": None,
        "numero_solicitud_consistente": None,
        "firmas_completas": None,
    }
    alertas = []
    
    # --- Validar nombre consistente ---
    nombres = []
    if "CARTA_SOLICITUD" in documentos:
        nombre_carta = documentos["CARTA_SOLICITUD"]["datos"].get("nombre_solicitante")
        if nombre_carta:
            nombres.append(("CARTA_SOLICITUD", nombre_carta))
    
    if "AUTORIZACION_SEGUROS" in documentos:
        nombre_auth = documentos["AUTORIZACION_SEGUROS"]["datos"].get("nombre_solicitante")
        if nombre_auth:
            nombres.append(("AUTORIZACION_SEGUROS", nombre_auth))
    
    if len(nombres) >= 2:
        # Comparar nombres (permitir variaciones menores por OCR)
        nombre1 = nombres[0][1].upper().split()
        nombre2 = nombres[1][1].upper().split()
        
        # Contar palabras en común
        palabras_comunes = sum(1 for p in nombre1 if p in nombre2)
        total_palabras = max(len(nombre1), len(nombre2))
        
        if palabras_comunes >= total_palabras * 0.7:
            validaciones["nombre_consistente"] = True
        else:
            validaciones["nombre_consistente"] = False
            alertas.append(f"Nombre inconsistente: '{nombres[0][1]}' vs '{nombres[1][1]}'")
    elif len(nombres) == 1:
        validaciones["nombre_consistente"] = True  # Solo hay uno, OK
    else:
        validaciones["nombre_consistente"] = None
        alertas.append("No se encontró nombre del solicitante")
    
    # --- Validar número de solicitud consistente ---
    numeros = []
    for tipo in ["AUTORIZACION_SEGUROS", "DIVULGACIONES_TITULO", "DIVULGACIONES_PRODUCTOS"]:
        if tipo in documentos:
            num = documentos[tipo]["datos"].get("num_solicitud")
            if num:
                numeros.append((tipo, num))
    
    if len(numeros) >= 2:
        numeros_unicos = set(n[1] for n in numeros)
        if len(numeros_unicos) == 1:
            validaciones["numero_solicitud_consistente"] = True
        else:
            validaciones["numero_solicitud_consistente"] = False
            alertas.append(f"Números de solicitud inconsistentes: {numeros}")
    elif len(numeros) == 1:
        validaciones["numero_solicitud_consistente"] = True
    else:
        validaciones["numero_solicitud_consistente"] = None
        alertas.append("No se encontró número de solicitud")
    
    # --- Validar firmas completas ---
    firmas_requeridas = ["AUTORIZACION_SEGUROS", "DIVULGACIONES_TITULO", "DIVULGACIONES_PRODUCTOS"]
    firmas_faltantes = []
    
    for tipo in firmas_requeridas:
        if tipo in documentos:
            firma = documentos[tipo]["datos"].get("firma", {})
            if not firma.get("presente", False):
                firmas_faltantes.append(tipo)
    
    if not firmas_faltantes:
        validaciones["firmas_completas"] = True
    else:
        validaciones["firmas_completas"] = False
        for tipo in firmas_faltantes:
            alertas.append(f"Falta firma en {tipo}")
    
    return validaciones, alertas


# =============================================================================
# FUNCIÓN: GENERAR REPORTE
# =============================================================================

def generar_reporte(archivo, documentos, num_paginas, validaciones, alertas):
    """
    Genera el reporte estructurado del paquete de documentos.
    """
    # Determinar estado general
    if validaciones["nombre_consistente"] and validaciones["numero_solicitud_consistente"] and validaciones["firmas_completas"]:
        resumen = "APROBADO"
    elif alertas:
        resumen = "REVISIÓN REQUERIDA"
    else:
        resumen = "INCOMPLETO"
    
    reporte = {
        "archivo": os.path.basename(archivo),
        "total_paginas": num_paginas,
        "resumen_validacion": resumen,
        "documentos_detectados": documentos,
        "validaciones": validaciones,
        "alertas": alertas,
    }
    
    return reporte


# =============================================================================
# FUNCIONES DEL PIPELINE
# =============================================================================

def sanitizar_nombre(nombre_pdf):
    """
    Convierte nombre de PDF a nombre seguro para archivos.
    'COTIZACION 1911 CV (2).pdf' -> 'COTIZACION_1911_CV_2'
    """
    # Quitar extensión
    nombre = os.path.splitext(nombre_pdf)[0]
    # Reemplazar caracteres problemáticos por _
    nombre = re.sub(r'[^\w\-]', '_', nombre)
    # Eliminar guiones bajos múltiples
    nombre = re.sub(r'_+', '_', nombre)
    # Quitar _ al inicio y final
    nombre = nombre.strip('_')
    return nombre


def crear_carpetas():
    """Crea todas las carpetas necesarias si no existen."""
    for nombre, carpeta in CARPETAS.items():
        if not os.path.exists(carpeta):
            os.makedirs(carpeta)
            print(f"  Carpeta creada: {carpeta}/")


def inicializar_log():
    """Crea el archivo de log CSV si no existe."""
    # Asegurar que exista la carpeta de logs
    if not os.path.exists(CARPETAS["logs"]):
        os.makedirs(CARPETAS["logs"])
    
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("archivo;etapa;resultado;timestamp;mensaje;intento_num\n")


def escribir_log(archivo, etapa, resultado, mensaje="-", intento_num=1):
    """Escribe una entrada en el log CSV."""
    timestamp = datetime.now().isoformat()
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{archivo};{etapa};{resultado};{timestamp};{mensaje};{intento_num}\n")


def contar_errores(archivo):
    """Cuenta cuántos errores tiene un archivo en el log."""
    if not os.path.exists(LOG_FILE):
        return 0
    
    errores = 0
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for linea in f:
            partes = linea.strip().split(";")
            if len(partes) >= 3 and partes[0] == archivo and partes[2] == "ERROR":
                errores += 1
    return errores


def obtener_ultimo_intento(archivo, etapa):
    """Obtiene el número del último intento para una etapa específica."""
    if not os.path.exists(LOG_FILE):
        return 0
    
    ultimo_intento = 0
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for linea in f:
            partes = linea.strip().split(";")
            if len(partes) >= 6 and partes[0] == archivo and partes[1] == etapa:
                try:
                    intento = int(partes[5])
                    if intento > ultimo_intento:
                        ultimo_intento = intento
                except:
                    pass
    return ultimo_intento


def limpiar_tmp_huerfanos():
    """Borra archivos .tmp con más de 1 hora de antigüedad."""
    carpeta = CARPETAS["resultados"]
    if not os.path.exists(carpeta):
        return
    
    ahora = time.time()
    for tmp in glob(os.path.join(carpeta, "*.tmp")):
        try:
            edad = ahora - os.path.getmtime(tmp)
            if edad > MAX_EDAD_TMP:
                os.remove(tmp)
                print(f"  Limpiado .tmp huérfano: {os.path.basename(tmp)}")
        except Exception as e:
            print(f"  Error limpiando {tmp}: {e}")


def mover_archivo(origen, destino):
    """Mueve un archivo de una carpeta a otra."""
    if os.path.exists(origen):
        # Si ya existe en destino, eliminarlo primero
        if os.path.exists(destino):
            os.remove(destino)
        shutil.move(origen, destino)
        return True
    return False


def hacer_ocr(nombre_pdf, ruta_entrada, ruta_salida):
    """
    Aplica OCR a un PDF.
    
    Returns:
        True si fue exitoso, False si falló.
    """
    try:
        resultado = convertir_pdf_a_searchable(ruta_entrada, ruta_salida)
        return resultado is not None
    except Exception as e:
        raise Exception(f"Error en OCR: {str(e)}")


def generar_txt_desde_reporte(reporte, ruta_txt):
    """
    Genera un archivo TXT legible a partir del reporte.
    """
    with open(ruta_txt, "w", encoding="utf-8") as f:
        f.write("REPORTE DE VERIFICACIÓN DE PRÉSTAMOS\n")
        f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 60 + "\n\n")
        
        f.write(f"Archivo: {reporte['archivo']}\n")
        f.write(f"Estado: {reporte['resumen_validacion']}\n")
        f.write(f"Páginas: {reporte['total_paginas']}\n\n")
        
        f.write("DOCUMENTOS DETECTADOS:\n")
        for tipo, info in reporte['documentos_detectados'].items():
            f.write(f"  {tipo} (Páginas {info['paginas']}):\n")
            for campo, valor in info['datos'].items():
                if isinstance(valor, dict):
                    f.write(f"    {campo}: {valor}\n")
                else:
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


def generar_json_pipeline(nombre_pdf, ruta_pdf_ocr, ruta_json_final, ruta_txt_final):
    """
    Genera el JSON y TXT a partir del PDF con OCR.
    Usa escritura atómica (.tmp -> .json/.txt).
    
    Returns:
        True si fue exitoso, False si falló.
    """
    ruta_tmp_json = ruta_json_final + ".tmp"
    ruta_tmp_txt = ruta_txt_final + ".tmp"
    
    try:
        # Procesar el paquete
        documentos, num_paginas = procesar_paquete(ruta_pdf_ocr)
        
        # Validar consistencia
        validaciones, alertas = validar_consistencia(documentos)
        
        # Generar reporte
        reporte = generar_reporte(ruta_pdf_ocr, documentos, num_paginas, validaciones, alertas)
        
        # Escribir JSON a archivo temporal
        with open(ruta_tmp_json, "w", encoding="utf-8") as f:
            json.dump(reporte, f, indent=2, ensure_ascii=False)
        
        # Escribir TXT a archivo temporal
        generar_txt_desde_reporte(reporte, ruta_tmp_txt)
        
        # Renombrar a archivos finales (atómico)
        os.rename(ruta_tmp_json, ruta_json_final)
        os.rename(ruta_tmp_txt, ruta_txt_final)
        
        return True
        
    except Exception as e:
        # Limpiar .tmp si existen
        for tmp in [ruta_tmp_json, ruta_tmp_txt]:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except:
                    pass
        raise Exception(f"Error generando JSON/TXT: {str(e)}")


def procesar_pdf_pipeline(nombre_pdf, skip_ocr=False):
    """
    Procesa un PDF individual a través del pipeline completo.
    
    Args:
        nombre_pdf: Nombre del archivo PDF en Cotizaciones/
        skip_ocr: Si es True, salta el paso de OCR y usa el PDF existente en Cotizaciones_OCR/
    
    Returns:
        str: Estado final ("OK", "ERROR", "IGNORADO", "LIMITE_ERRORES")
    """
    nombre_sanitizado = sanitizar_nombre(nombre_pdf)
    
    # Nombre del archivo OCR (con sufijo _OCR)
    nombre_base, extension = os.path.splitext(nombre_pdf)
    nombre_ocr = f"{nombre_base}_OCR{extension}"
    
    # Rutas
    ruta_entrada = os.path.join(CARPETAS["entrada"], nombre_pdf)
    ruta_ocr = os.path.join(CARPETAS["ocr"], nombre_ocr)  # Con sufijo _OCR
    ruta_json = os.path.join(CARPETAS["resultados"], f"{nombre_sanitizado}.json")
    ruta_txt = os.path.join(CARPETAS["resultados_txt"], f"{nombre_sanitizado}.txt")
    ruta_error = os.path.join(CARPETAS["error"], nombre_pdf)
    
    print(f"\n{'='*60}")
    print(f"Procesando: {nombre_pdf}")
    print(f"  Nombre sanitizado: {nombre_sanitizado}")
    
    # --- Verificar si ya existe JSON ---
    if os.path.exists(ruta_json):
        print(f"  [--] JSON ya existe, ignorando")
        return "IGNORADO"
    
    # --- Verificar límite de errores ---
    errores = contar_errores(nombre_pdf)
    if errores >= MAX_ERRORES:
        print(f"  [!!] Límite de errores alcanzado ({errores}), moviendo a Error/")
        mover_archivo(ruta_entrada, ruta_error)
        escribir_log(nombre_pdf, "MOVIDO_ERROR", "LIMITE", f"{errores} errores acumulados", "-")
        return "LIMITE_ERRORES"
    
    # --- Paso 1: OCR ---
    if skip_ocr:
        # Modo skip-ocr: usar PDF original o existente OCR
        if os.path.exists(ruta_ocr):
            print(f"  [--] Usando OCR existente (--skip-ocr)")
        else:
            # Usar el PDF original directamente
            print(f"  [--] Sin OCR disponible, usando PDF original (--skip-ocr)")
            ruta_ocr = ruta_entrada
    elif not os.path.exists(ruta_ocr):
        print(f"  [>>] Paso 1: Aplicando OCR...")
        intento = obtener_ultimo_intento(nombre_pdf, "OCR") + 1
        
        if not OCR_DISPONIBLE:
            print(f"  [ERROR] OCR no disponible: faltan dependencias")
            escribir_log(nombre_pdf, "OCR", "ERROR", "Dependencias OCR no instaladas", intento)
            return "ERROR"
        
        try:
            exito = hacer_ocr(nombre_pdf, ruta_entrada, ruta_ocr)
            if exito:
                print(f"  [OK] OCR completado")
                escribir_log(nombre_pdf, "OCR", "OK", "-", intento)
            else:
                raise Exception("OCR retornó None")
        except Exception as e:
            print(f"  [ERROR] Error en OCR: {e}")
            escribir_log(nombre_pdf, "OCR", "ERROR", str(e)[:100], intento)
            return "ERROR"
    else:
        print(f"  [--] OCR ya existe, saltando paso 1")
    
    # --- Paso 2: Generar JSON y TXT ---
    print(f"  [>>] Paso 2: Generando JSON y TXT...")
    intento = obtener_ultimo_intento(nombre_pdf, "JSON") + 1
    
    try:
        exito = generar_json_pipeline(nombre_pdf, ruta_ocr, ruta_json, ruta_txt)
        if exito:
            print(f"  [OK] JSON generado: {nombre_sanitizado}.json")
            print(f"  [OK] TXT generado: {nombre_sanitizado}.txt")
            escribir_log(nombre_pdf, "JSON", "OK", "-", intento)
            
            # PDF original se queda en Cotizaciones/
            return "OK"
        else:
            raise Exception("Generación de JSON/TXT retornó False")
    except Exception as e:
        print(f"  [ERROR] Error generando JSON: {e}")
        escribir_log(nombre_pdf, "JSON", "ERROR", str(e)[:100], intento)
        return "ERROR"


def ejecutar_pipeline(skip_ocr=False):
    """
    Ejecuta el pipeline completo para todos los PDFs pendientes.
    
    Args:
        skip_ocr: Si es True, salta el paso de OCR para todos los archivos.
    """
    print("="*60)
    print("PIPELINE DE PROCESAMIENTO DE COTIZACIONES")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if skip_ocr:
        print("Modo: --skip-ocr (sin aplicar OCR)")
    print("="*60)
    
    # --- Inicialización ---
    print("\n[1/3] Inicializando...")
    crear_carpetas()
    inicializar_log()
    
    # --- Limpieza ---
    print("\n[2/3] Limpiando archivos temporales...")
    limpiar_tmp_huerfanos()
    
    # --- Procesar PDFs ---
    print("\n[3/3] Procesando PDFs...")
    
    # Listar PDFs en carpeta de entrada
    patron = os.path.join(CARPETAS["entrada"], "*.pdf")
    pdfs = glob(patron)
    
    if not pdfs:
        print(f"\n  No hay PDFs en {CARPETAS['entrada']}/")
        print("  Coloca los PDFs a procesar en esa carpeta y ejecuta de nuevo.")
        return
    
    print(f"\n  Encontrados {len(pdfs)} PDFs para procesar")
    
    # Contadores
    resultados = {
        "OK": 0,
        "ERROR": 0,
        "IGNORADO": 0,
        "LIMITE_ERRORES": 0,
    }
    
    # Procesar cada PDF
    for ruta_pdf in pdfs:
        nombre_pdf = os.path.basename(ruta_pdf)
        resultado = procesar_pdf_pipeline(nombre_pdf, skip_ocr=skip_ocr)
        resultados[resultado] = resultados.get(resultado, 0) + 1
    
    # --- Resumen ---
    print("\n" + "="*60)
    print("RESUMEN DEL PIPELINE")
    print("="*60)
    print(f"  [OK] Procesados OK:     {resultados['OK']}")
    print(f"  [--] Ignorados:         {resultados['IGNORADO']}")
    print(f"  [XX] Errores:           {resultados['ERROR']}")
    print(f"  [!!] Límite errores:    {resultados['LIMITE_ERRORES']}")
    print("="*60)
    print(f"\nJSONs listos en: {CARPETAS['resultados']}/")
    print(f"Log de estado en: {LOG_FILE}")


def inicializar_estructura():
    """
    Inicializa la estructura de carpetas del pipeline.
    Mueve PDFs existentes a las carpetas correspondientes.
    """
    print("="*60)
    print("INICIALIZADOR DE ESTRUCTURA DEL PIPELINE")
    print("="*60)
    
    # --- Crear carpetas ---
    print("\n[1/2] Creando carpetas...")
    for carpeta in CARPETAS.values():
        if not os.path.exists(carpeta):
            os.makedirs(carpeta)
            print(f"  [OK] Creada: {carpeta}/")
        else:
            print(f"  [--] Ya existe: {carpeta}/")
    
    # --- Mover PDFs existentes ---
    print("\n[2/2] Buscando PDFs en la raíz para mover...")
    
    # Buscar PDFs en la carpeta actual (raíz)
    pdfs_raiz = [f for f in glob("*.pdf") if not f.endswith("_OCR.pdf")]
    pdfs_ocr = glob("*_OCR.pdf")
    
    if pdfs_raiz:
        print(f"\n  Encontrados {len(pdfs_raiz)} PDFs originales:")
        for pdf in pdfs_raiz:
            destino = os.path.join(CARPETAS["entrada"], pdf)
            if not os.path.exists(destino):
                shutil.move(pdf, destino)
                print(f"    [OK] Movido: {pdf} -> {CARPETAS['entrada']}/")
            else:
                print(f"    [--] Ya existe en destino: {pdf}")
    else:
        print("  No hay PDFs originales en la raíz para mover.")
    
    if pdfs_ocr:
        print(f"\n  Encontrados {len(pdfs_ocr)} PDFs con OCR:")
        for pdf in pdfs_ocr:
            destino = os.path.join(CARPETAS["ocr"], pdf)
            if not os.path.exists(destino):
                shutil.move(pdf, destino)
                print(f"    [OK] Movido: {pdf} -> {CARPETAS['ocr']}/")
            else:
                print(f"    [--] Ya existe en destino: {pdf}")
    else:
        print("  No hay PDFs con OCR en la raíz para mover.")
    
    # --- Resumen ---
    print("\n" + "="*60)
    print("ESTRUCTURA LISTA")
    print("="*60)
    print(f"""
Estructura de carpetas:

{CARPETAS['entrada']}/           <- PDFs originales (se quedan aquí)
{CARPETAS['ocr']}/       <- PDFs con OCR aplicado (automático)
{CARPETAS['error']}/     <- PDFs problemáticos (automático)
{CARPETAS['resultados']}/  <- JSONs para el RPA (automático)
{CARPETAS['resultados_txt']}/         <- TXTs legibles (automático)
{CARPETAS['logs']}/                   <- Logs de estado (automático)

Próximo paso:
    1. Coloca los PDFs a procesar en {CARPETAS['entrada']}/
    2. Ejecuta: python verificar_prestamos_v3.py --pipeline
""")


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def procesar_archivo_individual(archivo_entrada, directorio_salida):
    """
    Procesa un único archivo PDF y guarda el resultado en el directorio especificado.
    Retorna True si fue exitoso, False en caso contrario.
    """
    print("=" * 60)
    print(f"Procesando: {archivo_entrada}")
    
    try:
        # Procesar el paquete
        documentos, num_paginas = procesar_paquete(archivo_entrada)
        
        # Validar consistencia
        validaciones, alertas = validar_consistencia(documentos)
        
        # Generar reporte
        reporte = generar_reporte(archivo_entrada, documentos, num_paginas, validaciones, alertas)
        
        # Mostrar resultado
        print(json.dumps(reporte, indent=2, ensure_ascii=False))
        print("-" * 60)
        
        # Crear directorio de salida si no existe
        os.makedirs(directorio_salida, exist_ok=True)
        
        # Generar nombre de archivo de salida basado en el nombre del PDF
        base_name = os.path.splitext(os.path.basename(archivo_entrada))[0]
        # Quitar _OCR del nombre si existe
        if base_name.endswith('_OCR'):
            base_name = base_name[:-4]
        
        json_path = os.path.join(directorio_salida, f"{base_name}_resultado.json")
        txt_path = os.path.join(directorio_salida, f"{base_name}_resultado.txt")
        
        # Guardar JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(reporte, f, indent=2, ensure_ascii=False)
        
        # Guardar TXT legible
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("REPORTE DE VERIFICACIÓN DE PRÉSTAMO\n")
            f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            
            f.write(f"Archivo: {reporte['archivo']}\n")
            f.write(f"Estado: {reporte['resumen_validacion']}\n")
            f.write(f"Páginas: {reporte['total_paginas']}\n\n")
            
            f.write("DOCUMENTOS DETECTADOS:\n")
            for tipo, info in reporte['documentos_detectados'].items():
                f.write(f"  {tipo} (Páginas {info['paginas']}):\n")
                for campo, valor in info['datos'].items():
                    if isinstance(valor, dict):
                        f.write(f"    {campo}: {valor}\n")
                    else:
                        f.write(f"    {campo}: {valor}\n")
                f.write("\n")
            
            f.write("VALIDACIONES:\n")
            for val, estado in reporte['validaciones'].items():
                f.write(f"  {val}: {estado}\n")
            
            if reporte['alertas']:
                f.write("\nALERTAS:\n")
                for alerta in reporte['alertas']:
                    f.write(f"  [!] {alerta}\n")
        
        print(f"\nResultados guardados en:")
        print(f"  - {json_path}")
        print(f"  - {txt_path}")
        
        # Retornar código basado en validación
        return reporte['resumen_validacion'] == 'APROBADO'
        
    except Exception as e:
        print(f"  ERROR procesando {archivo_entrada}: {e}")
        traceback.print_exc()
        return False


def main():
    """Función principal del script."""
    # Configurar argumentos de línea de comandos
    parser = argparse.ArgumentParser(
        description='Verifica paquetes de documentos de préstamos.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Modos de operación:
  --init               Inicializa la estructura de carpetas del pipeline
  --pipeline           Ejecuta el pipeline completo (OCR + verificación)
  --pipeline --skip-ocr  Ejecuta pipeline sin aplicar OCR (usa PDFs existentes)
  --input <archivo>    Procesa un archivo individual (para Power Automate)
  (sin argumentos)     Modo legacy: procesa PDFs en directorio actual

Ejemplos:
  python verificar_prestamos_v3.py --init
  python verificar_prestamos_v3.py --pipeline
  python verificar_prestamos_v3.py --pipeline --skip-ocr
  python verificar_prestamos_v3.py --input archivo.pdf --output-dir carpeta
"""
    )
    parser.add_argument('--input', '-i', type=str, help='Archivo PDF a verificar')
    parser.add_argument('--output-dir', '-o', type=str, help='Directorio de salida para los resultados')
    parser.add_argument('--init', action='store_true', 
                        help='Inicializa la estructura de carpetas del pipeline')
    parser.add_argument('--pipeline', action='store_true',
                        help='Ejecuta el pipeline completo (OCR + verificación)')
    parser.add_argument('--skip-ocr', action='store_true',
                        help='Salta el paso de OCR (usar con --pipeline)')
    
    args = parser.parse_args()
    
    # ===== Modo --init: Inicializar estructura =====
    if args.init:
        inicializar_estructura()
        return
    
    # ===== Modo --pipeline: Ejecutar pipeline completo =====
    if args.pipeline:
        if not OCR_DISPONIBLE and not args.skip_ocr:
            print("[!] Advertencia: Dependencias de OCR no disponibles.")
            print("    Instale: pip install pypdfium2 pytesseract Pillow PyPDF2")
            print("    O use --skip-ocr para procesar sin aplicar OCR.\n")
        ejecutar_pipeline(skip_ocr=args.skip_ocr)
        return
    
    # ===== Modo con argumentos --input (para Power Automate) =====
    if args.input:
        if not os.path.exists(args.input):
            print(f"[X] Archivo no encontrado: {args.input}")
            sys.exit(1)
        
        output_dir = args.output_dir if args.output_dir else '.'
        exito = procesar_archivo_individual(args.input, output_dir)
        sys.exit(0 if exito else 2)  # 0=APROBADO, 2=REVISIÓN REQUERIDA o error
    
    # Modo legacy (buscar archivos en directorio actual)
    archivos_ocr = glob.glob("*_OCR.pdf")
    
    if archivos_ocr:
        print("Usando archivos con OCR integrado (_OCR.pdf)\n")
        archivos = archivos_ocr
    else:
        archivos = [f for f in glob.glob("*.pdf") if not f.endswith("_OCR.pdf")]
        if archivos:
            print("ADVERTENCIA: No se encontraron archivos _OCR.pdf")
            print("Usando archivos originales (puede haber errores de extracción)\n")
    
    if not archivos:
        print("No se encontraron archivos PDF para procesar.")
        print("Uso: python verificar_prestamos_v3.py --input archivo.pdf --output-dir carpeta")
        return
    
    reportes = []
    
    for archivo in archivos:
        print("=" * 60)
        print(f"Procesando: {archivo}")
        
        try:
            # Procesar el paquete
            documentos, num_paginas = procesar_paquete(archivo)
            
            # Validar consistencia
            validaciones, alertas = validar_consistencia(documentos)
            
            # Generar reporte
            reporte = generar_reporte(archivo, documentos, num_paginas, validaciones, alertas)
            reportes.append(reporte)
            
            # Mostrar resultado
            print(json.dumps(reporte, indent=2, ensure_ascii=False))
            print("-" * 60)
            
        except Exception as e:
            print(f"  ERROR procesando {archivo}: {e}")
            traceback.print_exc()
    
    # Guardar reportes
    if reportes:
        # JSON
        with open("reporte_verificacion.json", "w", encoding="utf-8") as f:
            json.dump(reportes, f, indent=2, ensure_ascii=False)
        
        # TXT legible
        with open("reporte_verificacion.txt", "w", encoding="utf-8") as f:
            f.write("REPORTE DE VERIFICACIÓN DE PRÉSTAMOS\n")
            f.write(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            
            for reporte in reportes:
                f.write(f"Archivo: {reporte['archivo']}\n")
                f.write(f"Estado: {reporte['resumen_validacion']}\n")
                f.write(f"Páginas: {reporte['total_paginas']}\n\n")
                
                f.write("DOCUMENTOS DETECTADOS:\n")
                for tipo, info in reporte['documentos_detectados'].items():
                    f.write(f"  {tipo} (Páginas {info['paginas']}):\n")
                    for campo, valor in info['datos'].items():
                        if isinstance(valor, dict):
                            f.write(f"    {campo}: {valor}\n")
                        else:
                            f.write(f"    {campo}: {valor}\n")
                    f.write("\n")
                
                f.write("VALIDACIONES:\n")
                for val, estado in reporte['validaciones'].items():
                    f.write(f"  {val}: {estado}\n")
                
                if reporte['alertas']:
                    f.write("\nALERTAS:\n")
                    for alerta in reporte['alertas']:
                        f.write(f"  [!] {alerta}\n")
                
                f.write("\n" + "=" * 60 + "\n\n")
        
        print("\n" + "=" * 60)
        print("Reportes guardados en:")
        print("  - reporte_verificacion.txt")
        print("  - reporte_verificacion.json")


if __name__ == "__main__":
    main()

