"""
Detector de Firmas Universal - v1.0
Detecta firmas electrónicas, manuscritas y de texto en cualquier documento PDF.

Uso:
    python detector_firmas.py documento.pdf              # Analiza un documento
    python detector_firmas.py carpeta/                   # Analiza todos los PDFs en una carpeta
    
    # Como módulo:
    from detector_firmas import analizar_documento, detectar_firma_en_pagina
"""

import fitz  # PyMuPDF
import re
import json
import glob
import os
import sys
from datetime import datetime

# Intentar importar OpenCV para detección de firmas manuscritas
try:
    import cv2
    import numpy as np
    OPENCV_DISPONIBLE = True
except ImportError:
    OPENCV_DISPONIBLE = False
    print("[!] OpenCV no disponible. Instalar con: pip install opencv-python-headless")
    print("    La detección de firmas manuscritas estará limitada.\n")


# =============================================================================
# CONFIGURACIÓN DE DETECCIÓN
# =============================================================================

# Palabras clave que indican áreas de firma (configurable)
PALABRAS_AREA_FIRMA = [
    "Firma del Solicitante",
    "Firma del Cliente",
    "Firma",
    "Signature",
    "Signed",
    "Firmado",
]

# Palabras que indican que hay una declaración/certificación (antes de firma)
PALABRAS_CERTIFICACION = [
    "Certifico",
    "Certify",
    "Declaro",
    "Declare",
    "Acepto",
    "Accept",
    "Autorizo",
    "Authorize",
]


# =============================================================================
# DETECCIÓN DE FIRMA MANUSCRITA (OpenCV)
# =============================================================================

def detectar_firma_manuscrita_en_area(page, area_texto="Firma", margen_arriba=100, margen_lados=50):
    """
    Detecta si hay una firma manuscrita en el área cercana a un texto específico.
    Usa OpenCV para analizar si hay trazos/líneas en esa área.
    
    Args:
        page: Objeto page de PyMuPDF
        area_texto: Texto que indica dónde buscar la firma
        margen_arriba: Píxeles a buscar arriba del texto
        margen_lados: Píxeles a buscar a los lados
    
    Returns:
        (tiene_firma, confianza, descripcion)
    """
    if not OPENCV_DISPONIBLE:
        return None, 0, "OpenCV no disponible"
    
    try:
        # Buscar el área donde está el texto indicador
        text_instances = page.search_for(area_texto)
        
        if not text_instances:
            # Intentar con otras palabras clave
            for palabra in PALABRAS_AREA_FIRMA:
                text_instances = page.search_for(palabra)
                if text_instances:
                    break
        
        if not text_instances:
            return None, 0, "Area de firma no encontrada"
        
        # Tomar la primera instancia
        rect = text_instances[0]
        
        # Expandir el área hacia arriba (donde está la firma)
        firma_rect = fitz.Rect(
            rect.x0 - margen_lados,
            rect.y0 - margen_arriba,
            rect.x1 + margen_lados + 100,
            rect.y0 - 5
        )
        
        # Asegurar que el rectángulo está dentro de la página
        page_rect = page.rect
        firma_rect = firma_rect & page_rect
        
        if firma_rect.is_empty:
            return None, 0, "Area de firma fuera de pagina"
        
        # Renderizar solo esa área como imagen
        mat = fitz.Matrix(3, 3)
        pix = page.get_pixmap(matrix=mat, clip=firma_rect)
        
        # Convertir a formato OpenCV
        img_data = pix.tobytes("png")
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            return None, 0, "Error al procesar imagen"
        
        # Convertir a escala de grises
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Aplicar umbral para detectar tinta
        _, thresh = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        # Contar píxeles de tinta
        pixeles_tinta = cv2.countNonZero(thresh)
        total_pixeles = thresh.shape[0] * thresh.shape[1]
        porcentaje_tinta = (pixeles_tinta / total_pixeles) * 100
        
        # Detectar contornos
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
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
# DETECCIÓN DE FIRMA ELECTRÓNICA (Timestamp)
# =============================================================================

def detectar_firma_electronica(texto):
    """
    Detecta firmas electrónicas con timestamp.
    Patrón típico: NOMBRE APELLIDO 10/10/2025 7:29 AM PDT
    
    Returns:
        (tiene_firma, tipo, detalle)
    """
    # Normalizar texto
    texto_norm = re.sub(r'\s+', ' ', texto)
    
    # Patrón 1: NOMBRE + fecha + hora + AM/PM + timezone
    patron_completo = r'([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]{3,40}?)\s*(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s*(?:PDT|PST|EST|CST|MST)?)?)'
    
    match = re.search(patron_completo, texto_norm, re.IGNORECASE)
    if match:
        nombre = match.group(1).strip()
        fecha = match.group(2)
        hora = match.group(3).strip()
        if len(nombre) > 5:
            return True, "Firma Electronica (Timestamp)", f"{nombre} - {fecha} {hora}"
    
    # Patrón 2: Solo fecha + hora cerca de "Firma" o "Certifico"
    if re.search(r'(Firma|Certifico|Signed|Certify)', texto_norm, re.IGNORECASE):
        patron_timestamp = r'(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s*(?:PDT|PST|EST|CST|MST)?)?)'
        match_ts = re.search(patron_timestamp, texto_norm)
        if match_ts:
            return True, "Firma Electronica (Timestamp)", match_ts.group(1)
    
    return False, None, None


# =============================================================================
# DETECCIÓN DE FIRMA DE TEXTO
# =============================================================================

def detectar_firma_texto(texto):
    """
    Detecta firmas de texto (nombre escrito después de certificación).
    
    Returns:
        (tiene_firma, tipo, detalle)
    """
    texto_norm = re.sub(r'\s+', ' ', texto)
    
    # Buscar nombre después de palabras de certificación
    for palabra in PALABRAS_CERTIFICACION:
        patron = rf'{palabra}[^A-Z]{{0,50}}([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]{{5,40}}?)(?:\d{{1,2}}/|\n|Firma|$)'
        match = re.search(patron, texto_norm, re.IGNORECASE)
        if match:
            nombre = match.group(1).strip()
            if len(nombre) > 5 and not any(p in nombre.upper() for p in ['DOCUMENTO', 'SEGURO', 'TITULO']):
                return True, "Firma de Texto", nombre
    
    return False, None, None


# =============================================================================
# DETECCIÓN DE MARCA X
# =============================================================================

def detectar_marca_x(texto):
    """
    Detecta marcas X como firma.
    
    Returns:
        (tiene_firma, tipo, detalle)
    """
    if re.search(r'[xX]{1,3}\s*(?:Firma|Signature|___|---)', texto):
        return True, "Firma con Marca X", "Marca X detectada"
    
    if re.search(r'(?:Firma|Signature)\s*[:\s]*[xX]{1,3}', texto):
        return True, "Firma con Marca X", "Marca X detectada"
    
    return False, None, None


# =============================================================================
# FUNCIÓN PRINCIPAL: DETECTAR FIRMA EN PÁGINA
# =============================================================================

def detectar_firma_en_pagina(page, texto=None):
    """
    Detecta cualquier tipo de firma en una página.
    Combina todos los métodos de detección.
    
    Args:
        page: Objeto page de PyMuPDF
        texto: Texto de la página (opcional, se extrae si no se provee)
    
    Returns:
        dict con información de la firma detectada
    """
    if texto is None:
        texto = page.get_text()
    
    resultado = {
        "firma_detectada": False,
        "tipo": None,
        "detalle": None,
        "confianza": 0,
        "metodo": None
    }
    
    # 1. Intentar detectar firma electrónica (más confiable)
    tiene_firma, tipo, detalle = detectar_firma_electronica(texto)
    if tiene_firma:
        resultado.update({
            "firma_detectada": True,
            "tipo": tipo,
            "detalle": detalle,
            "confianza": 95,
            "metodo": "electronica"
        })
        return resultado
    
    # 2. Intentar detectar marca X
    tiene_firma, tipo, detalle = detectar_marca_x(texto)
    if tiene_firma:
        resultado.update({
            "firma_detectada": True,
            "tipo": tipo,
            "detalle": detalle,
            "confianza": 80,
            "metodo": "marca_x"
        })
        return resultado
    
    # 3. Intentar detectar firma de texto
    tiene_firma, tipo, detalle = detectar_firma_texto(texto)
    if tiene_firma:
        resultado.update({
            "firma_detectada": True,
            "tipo": tipo,
            "detalle": detalle,
            "confianza": 70,
            "metodo": "texto"
        })
        return resultado
    
    # 4. Intentar detectar firma manuscrita (si hay área de firma identificada)
    if OPENCV_DISPONIBLE:
        for palabra in PALABRAS_AREA_FIRMA:
            if palabra.lower() in texto.lower():
                tiene_firma, confianza, detalle = detectar_firma_manuscrita_en_area(page, palabra)
                if tiene_firma and confianza > 40:
                    resultado.update({
                        "firma_detectada": True,
                        "tipo": "Firma Manuscrita",
                        "detalle": detalle,
                        "confianza": confianza,
                        "metodo": "manuscrita_area"
                    })
                    return resultado
        
        # 5. Buscar firma manuscrita en toda la página (último recurso)
        tiene_firma, confianza, detalle = detectar_firma_manuscrita_pagina_completa(page)
        if tiene_firma and confianza > 50:
            resultado.update({
                "firma_detectada": True,
                "tipo": "Posible Firma Manuscrita",
                "detalle": detalle,
                "confianza": confianza,
                "metodo": "manuscrita_pagina"
            })
            return resultado
    
    # No se encontró firma
    resultado["detalle"] = "No se detectó firma"
    return resultado


# =============================================================================
# FUNCIÓN: ANALIZAR DOCUMENTO COMPLETO
# =============================================================================

def analizar_documento(pdf_path):
    """
    Analiza un documento PDF completo y detecta firmas en cada página.
    
    Args:
        pdf_path: Ruta al archivo PDF
    
    Returns:
        dict con el análisis completo del documento
    """
    if not os.path.exists(pdf_path):
        return {"error": f"Archivo no encontrado: {pdf_path}"}
    
    doc = fitz.open(pdf_path)
    num_paginas = len(doc)
    
    resultado = {
        "archivo": os.path.basename(pdf_path),
        "total_paginas": num_paginas,
        "fecha_analisis": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "paginas": [],
        "resumen": {
            "firmas_encontradas": 0,
            "paginas_con_firma": [],
            "tipos_firma": []
        }
    }
    
    print(f"Analizando: {pdf_path}")
    print(f"  Paginas: {num_paginas}")
    
    for i in range(num_paginas):
        page = doc[i]
        texto = page.get_text()
        
        firma_info = detectar_firma_en_pagina(page, texto)
        firma_info["pagina"] = i + 1
        
        resultado["paginas"].append(firma_info)
        
        if firma_info["firma_detectada"]:
            resultado["resumen"]["firmas_encontradas"] += 1
            resultado["resumen"]["paginas_con_firma"].append(i + 1)
            if firma_info["tipo"] not in resultado["resumen"]["tipos_firma"]:
                resultado["resumen"]["tipos_firma"].append(firma_info["tipo"])
            
            print(f"  Pagina {i+1}: {firma_info['tipo']} - {firma_info['detalle']}")
        else:
            print(f"  Pagina {i+1}: Sin firma detectada")
    
    doc.close()
    
    return resultado


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def main():
    """Función principal para uso desde línea de comandos."""
    
    if len(sys.argv) < 2:
        print("Uso: python detector_firmas.py <archivo.pdf | carpeta>")
        print("\nEjemplos:")
        print("  python detector_firmas.py documento.pdf")
        print("  python detector_firmas.py ./cotizaciones/")
        sys.exit(1)
    
    ruta = sys.argv[1]
    resultados = []
    
    # Determinar si es archivo o carpeta
    if os.path.isfile(ruta):
        archivos = [ruta]
    elif os.path.isdir(ruta):
        archivos = glob.glob(os.path.join(ruta, "*.pdf"))
        if not archivos:
            print(f"No se encontraron archivos PDF en: {ruta}")
            sys.exit(1)
    else:
        print(f"Ruta no valida: {ruta}")
        sys.exit(1)
    
    print("=" * 60)
    print("DETECTOR DE FIRMAS UNIVERSAL")
    print(f"OpenCV: {'Disponible' if OPENCV_DISPONIBLE else 'No disponible'}")
    print("=" * 60 + "\n")
    
    for archivo in archivos:
        resultado = analizar_documento(archivo)
        resultados.append(resultado)
        print()
    
    # Guardar reporte JSON
    reporte_path = os.path.join(os.path.dirname(archivos[0]), "reporte_firmas.json")
    with open(reporte_path, 'w', encoding='utf-8') as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    
    print("=" * 60)
    print(f"Reporte guardado en: {reporte_path}")
    print("=" * 60)
    
    # Resumen final
    print("\nRESUMEN:")
    for r in resultados:
        if "error" in r:
            print(f"  {r.get('archivo', 'Desconocido')}: ERROR - {r['error']}")
        else:
            print(f"  {r['archivo']}: {r['resumen']['firmas_encontradas']} firmas en paginas {r['resumen']['paginas_con_firma']}")


if __name__ == "__main__":
    main()
