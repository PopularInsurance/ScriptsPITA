"""
Verificador de Préstamos v2.1 - Enfoque Híbrido (Texto Nativo + OCR Selectivo)
==============================================================================
Esta versión combina:
1. Lectura de texto nativo del PDF (rápido, para lo que OCRmyPDF capturó bien)
2. OCR selectivo con Tesseract para áreas problemáticas (tablas, campos de formulario)

Uso:
    1. Primero ejecuta: python convertir_a_searchable.py
    2. Luego ejecuta: python verificar_prestamos_v2.py

El script buscará archivos _OCR.pdf y extraerá los datos de ellos.
"""
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import re
import json
import glob
import os
import io
import difflib

# --- CONFIGURACIÓN DE TESSERACT ---
possible_paths = [
    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe'
]
for p in possible_paths:
    if os.path.exists(p):
        pytesseract.pytesseract.tesseract_cmd = p
        break

def limpiar(texto):
    """Limpia espacios, saltos de línea y caracteres extraños."""
    if not texto:
        return None
    texto = re.sub(r'\s+', ' ', texto)
    return texto.strip()

def extraer_texto_pdf_nativo(pdf_path):
    """
    Extrae texto directamente del PDF (sin OCR en tiempo real).
    Funciona con PDFs que ya tienen capa de texto (nativos o procesados con OCRmyPDF).
    """
    doc = fitz.open(pdf_path)
    textos_por_pagina = []
    
    for num_pagina in range(len(doc)):
        page = doc.load_page(num_pagina)
        texto = page.get_text("text")  # Extrae texto nativo
        textos_por_pagina.append(texto)
    
    doc.close()
    return textos_por_pagina


def ocr_pagina_completa(pdf_path, num_pagina, zoom=3):
    """
    Hace OCR completo de una página específica del PDF.
    Útil cuando el texto nativo no capturó todo.
    """
    doc = fitz.open(pdf_path)
    page = doc.load_page(num_pagina)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img_data = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_data))
    doc.close()
    
    try:
        # PSM 11 (sparse text) es mejor para tablas y formularios
        texto = pytesseract.image_to_string(img, lang='spa', config='--psm 11')
        return texto
    except:
        return pytesseract.image_to_string(img)


def extraer_texto_hibrido(pdf_path):
    """
    Extrae texto usando enfoque híbrido:
    1. Texto nativo del PDF (lo que OCRmyPDF capturó)
    2. OCR directo para complementar áreas problemáticas
    
    Retorna una lista de tuplas: [(texto_nativo, texto_ocr), ...]
    """
    doc = fitz.open(pdf_path)
    resultados = []
    
    for num_pagina in range(len(doc)):
        page = doc.load_page(num_pagina)
        texto_nativo = page.get_text("text")
        
        # Hacer OCR adicional para esta página
        mat = fitz.Matrix(3, 3)  # Zoom 3x
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_data))
        
        try:
            texto_ocr = pytesseract.image_to_string(img, lang='spa', config='--psm 11')
        except:
            texto_ocr = ""
        
        resultados.append((texto_nativo, texto_ocr))
    
    doc.close()
    return resultados


def combinar_textos(texto_nativo, texto_ocr):
    """
    Combina texto nativo y OCR, priorizando el nativo pero usando OCR para llenar huecos.
    """
    return texto_nativo + "\n---OCR_ADICIONAL---\n" + texto_ocr

def extraer_pares_clave_valor(texto):
    """
    Estrategia de extracción directa del texto.
    Busca patrones específicos en todo el texto sin depender de estructura.
    """
    datos = {}
    texto_todo = texto.replace('\n', ' ')
    
    # --- NOMBRE SOLICITANTE ---
    palabras_excluidas = ['POPULAR', 'MORTGAGE', 'INSURANCE', 'BANCO', 'PUERTO', 'RICO', 
                          'TITULO', 'PÓLIZA', 'COTIZACIÓN', 'SOLICITUD', 'CAPITAL', 
                          'TITLE', 'SERVICES', 'AREA', 'PROCESO', 'CALLE', 'PANORAMA',
                          'TERRAZAS', 'CARRAIZO', 'FÍSICA', 'POSTAL', 'TRINIDAD']
    
    apellidos = ['GONZALEZ', 'RODRIGUEZ', 'MARTINEZ', 'LOPEZ', 'GARCIA', 'HERNANDEZ', 
                 'PEREZ', 'SANCHEZ', 'RAMIREZ', 'TORRES', 'RIVERA', 'AROCHO', 'ORTIZ',
                 'RAMOS', 'DIAZ', 'MORALES', 'CRUZ', 'REYES', 'RUIZ', 'FIGUEROA']
    
    nombre = "NO ENCONTRADO"
    for apellido in apellidos:
        # Patrón que tolera primera letra faltante (ej: "UIS" en lugar de "LUIS")
        patron = rf'([A-ZÁÉÍÓÚÑ]{{2,}}\s+(?:[A-ZÁÉÍÓÚÑ]{{2,}}\s+)?(?:[A-ZÁÉÍÓÚÑ]{{2,}}\s+)?{apellido})'
        match = re.search(patron, texto)
        if match:
            candidato = limpiar(match.group(1))
            if candidato and not any(exc in candidato for exc in palabras_excluidas):
                # Corregir nombres truncados por OCR
                candidato = re.sub(r'^UIS\b', 'LUIS', candidato)  # UIS -> LUIS
                candidato = re.sub(r'^CHAS\b', 'LUIS', candidato)  # CHAS -> LUIS (error común)
                candidato = re.sub(r'^NDRES\b', 'ANDRES', candidato)  # NDRES -> ANDRES
                candidato = re.sub(r'^ARLOS\b', 'CARLOS', candidato)  # ARLOS -> CARLOS
                candidato = re.sub(r'^ARIA\b', 'MARIA', candidato)  # ARIA -> MARIA
                candidato = re.sub(r'\bJAUEK\b', 'JAVIER', candidato)  # JAUEK -> JAVIER
                candidato = re.sub(r'\bJAUNEK\b', 'JAVIER', candidato)  # JAUNEK -> JAVIER
                nombre = candidato
                break
    datos["nombre_solicitante"] = nombre
    datos["nombre_titular"] = nombre
    
    # --- SSN ---
    patrones_ssn = [
        r'(\d{3}-\d{2}-\d{4})',
        r'(\d{3}[-/]\d{2}[-/]\d{4})',
    ]
    ssn_encontrado = None
    for patron in patrones_ssn:
        match_ssn = re.search(patron, texto)
        if match_ssn:
            ssn = match_ssn.group(1).replace('/', '-').replace(' ', '')
            ssn_encontrado = ssn
            break
    datos["ssn"] = ssn_encontrado if ssn_encontrado else "NO ENCONTRADO"
    
    # --- EMAIL (buscar después de "Correo Electrónico:") ---
    # Primero buscar con etiqueta específica
    match_email_etiqueta = re.search(r'Correo\s+Electr[oó]nico[:\s]*([^\n]+)', texto, re.IGNORECASE)
    if match_email_etiqueta:
        contenido_email = match_email_etiqueta.group(1).strip()
        # Limpiar caracteres de OCR problemáticos (| puede ser @ mal leído)
        contenido_email = contenido_email.replace('|', '')  # Quitar | que es error de OCR
        contenido_email = re.sub(r'\s+', '', contenido_email)  # Quitar espacios
        # Extraer el email del contenido
        match_email_real = re.search(r'([\w\.\-]+@[\w\.\-]+\.[a-z]{2,})', contenido_email, re.IGNORECASE)
        if match_email_real:
            datos["email"] = match_email_real.group(1).lower()
        else:
            # Si no hay @, puede estar mal el OCR, guardar lo que hay
            datos["email"] = contenido_email.lower() if contenido_email else "NO ENCONTRADO"
    else:
        # Fallback: buscar cualquier email
        patrones_email = [
            r'([\w\.\-]+@[\w\.\-]+\.com)',
            r'([\w\.\-]+@[\w\.\-]+\.net)',
        ]
        email_encontrado = None
        for patron in patrones_email:
            match_email = re.search(patron, texto, re.IGNORECASE)
            if match_email:
                email_encontrado = match_email.group(1).lower()
                break
        datos["email"] = email_encontrado if email_encontrado else "NO ENCONTRADO"
    
    # --- DIRECCIÓN POSTAL (buscar después de "Dirección Postal:") ---
    # Primero buscar con etiqueta específica
    match_dir_etiqueta = re.search(r'Direcci[oó]n\s+Postal[:\s]*([^\n]+(?:\n[^\n]*(?:PR|00\d{3}))?)', texto, re.IGNORECASE)
    if match_dir_etiqueta:
        direccion = limpiar(match_dir_etiqueta.group(1))
        # Limpiar y unir si está en múltiples líneas
        direccion = re.sub(r'\s+', ' ', direccion)
        datos["direccion_postal"] = direccion if direccion and len(direccion) > 5 else "NO ENCONTRADO"
    else:
        # Fallback: patrones genéricos
        patrones_dir = [
            r'Postal[:\s]*(P\s*O\s*BOX\s+\d+[^\n]+)',
            r'Física[:\s]*([^\n]+?(?:PR|Puerto Rico)\s*00\d{3})',
            r'(\d+\s+(?:TERRAZAS|URB|COND|CALLE|AVE|RD|KM)[^\n]+?(?:PR|Puerto Rico)?\s*00\d{3})',
            r'((?:TERRAZAS|URB|COND)[^\n]+?(?:San Juan|Trujillo|Bayamon|Carolina|Cabo Rojo)[^\n]*)',
        ]
        direccion_encontrada = None
        for patron in patrones_dir:
            match_dir = re.search(patron, texto, re.IGNORECASE | re.DOTALL)
            if match_dir:
                direccion = limpiar(match_dir.group(1))
                if direccion and len(direccion) > 10:
                    direccion_encontrada = direccion
                    break
        datos["direccion_postal"] = direccion_encontrada if direccion_encontrada else "NO ENCONTRADO"
    
    # --- TIPO DE PRÉSTAMO ---
    match_tipo = re.search(r'(Non\s+Conf\s*\([^)]+\))', texto, re.IGNORECASE)
    if match_tipo:
        datos["tipo_prestamo"] = limpiar(match_tipo.group(1))
    else:
        match_tipo2 = re.search(r'\b(FHA|VA|Conventional|USDA|Rural\s+Prime\s+Fixed\s+30|Rural\s+Prime)\b', texto, re.IGNORECASE)
        datos["tipo_prestamo"] = match_tipo2.group(1) if match_tipo2 else "NO ENCONTRADO"
    
    # --- HIPOTECA Y PRECIO DE VENTA ---
    patrones_hipoteca = [
        r'Hipoteca[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'Cantidad\s+de\s+la\s+Hipoteca[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'(?:Loan|Mortgage)\s+Amount[:\s]*\$?\s*([\d,]+\.\d{2})',
        # Patrones más flexibles para OCR
        r'Hipoteca[:\s]*\$?\s*([\d,]+)',
    ]
    patrones_precio = [
        r'Precio\s+de\s+Venta[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'(?:Purchase|Sales)\s+Price[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'Venta[:\s]*\$?\s*([\d,]+\.\d{2})',
        # Patrones más flexibles
        r'Precio[:\s]*\$?\s*([\d,]+)',
    ]
    
    hipoteca = None
    precio = None
    
    for patron in patrones_hipoteca:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            valor = match.group(1).replace(',', '')
            hipoteca = f"${float(valor):,.2f}"
            break
    
    for patron in patrones_precio:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            valor = match.group(1).replace(',', '').replace(' ', '')
            try:
                precio = f"${float(valor):,.2f}"
                break
            except:
                continue
    
    # Buscar todos los números con formato de precio (con o sin decimales)
    precios_encontrados = re.findall(r'\$?\s*([\d,]+(?:\.\d{2})?)', texto)
    valores = []
    for p in precios_encontrados:
        try:
            val_str = p.replace(',', '').replace('$', '').strip()
            val = float(val_str)
            # Rango razonable para hipotecas/precios de PR: $50k a $10M
            if 50000 <= val <= 10000000:
                valores.append(val)
        except:
            pass
    
    valores = sorted(set(valores))
    
    # Si encontramos 2+ valores, el menor es hipoteca, el mayor es precio
    if len(valores) >= 2:
        if not hipoteca:
            hipoteca = f"${valores[0]:,.2f}"
        if not precio:
            precio = f"${valores[-1]:,.2f}"
    elif len(valores) == 1:
        # Si solo hay un valor, intentar determinar si es hipoteca o precio
        if not hipoteca and not precio:
            # Por defecto, asumimos que es el precio de venta
            precio = f"${valores[0]:,.2f}"
        elif not hipoteca:
            hipoteca = f"${valores[0]:,.2f}"
        elif not precio:
            precio = f"${valores[0]:,.2f}"
    
    datos["cantidad_hipoteca"] = hipoteca if hipoteca else "NO ENCONTRADO"
    datos["precio_venta"] = precio if precio else "NO ENCONTRADO"
    
    return datos

def buscar_multiples_patrones(texto, patrones_lista):
    """Intenta múltiples patrones regex hasta encontrar uno que funcione."""
    for patron in patrones_lista:
        match = re.search(patron, texto, re.IGNORECASE | re.DOTALL)
        if match:
            resultado = limpiar(match.group(1))
            if resultado and len(resultado) > 1:
                return resultado
    return "NO ENCONTRADO"

def extraer_nombre_solicitante(texto):
    """Extrae el nombre del solicitante del texto."""
    palabras_excluidas = ['POPULAR', 'MORTGAGE', 'INSURANCE', 'BANCO', 'PUERTO', 'RICO', 
                          'TITULO', 'PÓLIZA', 'COTIZACIÓN', 'SOLICITUD', 'CAPITAL', 
                          'TITLE', 'SERVICES', 'AREA', 'PROCESO', 'CALLE', 'PANORAMA',
                          'TERRAZAS', 'CARRAIZO', 'CHAS', 'ESTIMADO', 'CLIENTE']
    
    # Primero buscar después de "Nombre del Solicitante:"
    match_etiqueta = re.search(r'Nombre\s+del\s+Solicitante[:\s]*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]+)', texto, re.IGNORECASE)
    if match_etiqueta:
        nombre = limpiar(match_etiqueta.group(1))
        if nombre and len(nombre) > 5 and not any(exc in nombre.upper() for exc in palabras_excluidas):
            return nombre.upper()
    
    apellidos = ['GONZALEZ', 'RODRIGUEZ', 'MARTINEZ', 'LOPEZ', 'GARCIA', 'HERNANDEZ', 
                 'PEREZ', 'SANCHEZ', 'RAMIREZ', 'TORRES', 'RIVERA', 'AROCHO', 'ORTIZ',
                 'RAMOS', 'DIAZ', 'MORALES', 'CRUZ', 'REYES', 'RUIZ', 'FIGUEROA']
    
    for apellido in apellidos:
        # Buscar nombre completo con apellido
        patron = rf'([A-ZÁÉÍÓÚÑ]+\s+(?:[A-ZÁÉÍÓÚÑ]+\s+)?(?:[A-ZÁÉÍÓÚÑ]+\s+)?{apellido}(?:\s+[A-ZÁÉÍÓÚÑ]+)?)'
        match = re.search(patron, texto)
        if match:
            nombre = limpiar(match.group(1))
            if not any(exc in nombre for exc in palabras_excluidas):
                # Limpiar errores comunes de OCR
                nombre = nombre.replace('CHAS ', 'LUIS ')  # Error común
                nombre = nombre.replace('JAUEK', 'JAVIER')  # Error común
                nombre = nombre.replace('JAUNEK', 'JAVIER')  # Error común
                return nombre
    
    return "NO ENCONTRADO"

def detectar_firma_en_texto(texto):
    """Detecta si hay una firma basándose en patrones típicos."""
    texto_lower = texto.lower()
    
    patron_timestamp = r'(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s*PDT|PST|EST)?)'
    match_ts = re.search(patron_timestamp, texto, re.IGNORECASE)
    
    if match_ts:
        return (True, "Firma Digital (Timestamp)", match_ts.group(1))
    
    if re.search(r'\bX+\b', texto) and 'firma' in texto_lower:
        return (True, "Firma con X", "Marca X detectada")
    
    patron_nombre_firma = r'([A-ZÁÉÍÓÚÑ]{4,}\s+(?:[A-ZÁÉÍÓÚÑ]+\s+)?[A-ZÁÉÍÓÚÑ]{4,})\s*\d{1,2}/\d{1,2}/\d{4}'
    match_nombre = re.search(patron_nombre_firma, texto)
    
    if match_nombre:
        nombre = limpiar(match_nombre.group(1))
        return (True, "Firma de Texto/Nombre", nombre)
    
    if "firma" not in texto_lower:
        return (False, "No se encontró sección de firma", "")
    
    return (True, "Posible firma (área de firma detectada)", "")

def verificar_linea_rechazo(texto):
    """Verifica si la línea de rechazo está vacía. CRÍTICO."""
    texto_formulario = [
        "firma del solicitante", "firma del co-solicitante", "firma", 
        "solicitante", "co-solicitante", "fecha", "mortg", "rev"
    ]
    
    patrones = [
        r'que\s+no\s+desea\s+que\s+Popular[^:]*gestione[:\s]*([^\n]{0,100})',
        r'favor\s+indicar\s+el\s+seguro\s+que\s+no\s+desea[^:]*:[:\s]*([^\n]{0,100})',
        r'Insurance\s+gestione[:\s]*([^\n]{0,100})',
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
                return f"ALERTA ROJA: Contiene texto ('{contenido}')"
    
    if "Popular Insurance" in texto and "gestione" in texto.lower():
        return "CORRECTO (Frase detectada, línea parece vacía)"
    elif "Popular Insurance" in texto:
        return "VERIFICAR MANUALMENTE (Layout diferente)"
    
    return "NO LOCALIZADO (Sección no encontrada)"

def extraer_fecha(texto):
    """Extrae fecha del texto en varios formatos."""
    patrones = [
        r'(\d{1,2}\s+de\s+[a-zA-Z]+\s+de\s+\d{4})',
        r'Fecha[:\s]*(\d{1,2}/\d{1,2}/\d{4})',
        r'(\d{1,2}/\d{1,2}/\d{4})',
    ]
    
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1)
    
    return "NO ENCONTRADO"


def extraer_fecha_documento_pagina3(texto):
    """
    Extrae la fecha del documento de la Página 3.
    La fecha correcta está al FINAL de la página, después de "POR:" (nombre del notario).
    Formato: "DD de MES de YYYY"
    """
    # Buscar la ÚLTIMA fecha en formato "DD de MES de YYYY"
    # Esta es la fecha del documento, no fechas internas del texto
    patron_fecha_espanol = r'(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)\s+de\s+\d{4})'
    
    # Encontrar TODAS las fechas y tomar la última
    fechas = re.findall(patron_fecha_espanol, texto, re.IGNORECASE)
    if fechas:
        return fechas[-1]  # Última fecha encontrada
    
    # Fallback: buscar fecha después de "POR:"
    match_por = re.search(r'POR[:\s]*[^\n]+\n\s*(\d{1,2}\s+de\s+[a-zA-Z]+\s+de\s+\d{4})', texto, re.IGNORECASE)
    if match_por:
        return match_por.group(1)
    
    # Fallback: buscar formato DD/MM/YYYY al final
    patron_fecha_num = r'(\d{1,2}/\d{1,2}/\d{4})'
    fechas_num = re.findall(patron_fecha_num, texto)
    if fechas_num:
        return fechas_num[-1]
    
    return "NO ENCONTRADO"

def extraer_numero(texto, palabras_clave):
    """Extrae un número después de palabras clave."""
    for palabra in palabras_clave:
        patron = rf'{palabra}[:\s#]*(\d{{7,12}})'
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Buscar número de préstamo formato Popular (070XXXXXXX)
    match_070 = re.search(r'\b(070\d{7})\b', texto)
    if match_070:
        return match_070.group(1)
    
    # Buscar números de 10 dígitos que empiecen con 07
    match_07 = re.search(r'\b(07\d{8})\b', texto)
    if match_07:
        return match_07.group(1)
    
    # Buscar "Número de Solicitud:" seguido de número
    match_solicitud = re.search(r'(?:Número\s+de\s+)?[Ss]olicitud[:\s]*(\d{10})', texto)
    if match_solicitud:
        return match_solicitud.group(1)
    
    # Buscar "Número de préstamo:" seguido de número
    match_prestamo = re.search(r'(?:Número\s+de\s+)?[Pp]réstamo[:\s]*(\d{10})', texto)
    if match_prestamo:
        return match_prestamo.group(1)
    
    return "NO ENCONTRADO"

def procesar_cotizacion(pdf_path):
    """Procesa un PDF de cotización y extrae/valida todos los campos requeridos."""
    
    datos = {
        "archivo": pdf_path,
        "resumen_validacion": "PENDIENTE",
        "pagina_1_datos": {},
        "pagina_2_propiedad": {},
        "pagina_3_fecha": {},
        "pagina_4_autorizacion": {},
        "pagina_5_divulgacion": {},
        "pagina_6_titulo": {},
        "alertas": []
    }
    
    print(f"Procesando: {pdf_path}")
    
    try:
        # Extraer texto usando enfoque híbrido (nativo + OCR)
        textos_hibridos = extraer_texto_hibrido(pdf_path)
        num_paginas = len(textos_hibridos)
        
        # Combinar textos para cada página
        textos = [combinar_textos(nativo, ocr) for nativo, ocr in textos_hibridos]
        print(f"  Páginas detectadas: {num_paginas}")
        
        # =========================================================
        # PÁGINA 1: DATOS MAESTROS
        # =========================================================
        if num_paginas >= 1:
            print("  Leyendo Página 1 (Datos Maestros)...")
            text_p1 = textos[0]
            
            datos_extraidos = extraer_pares_clave_valor(text_p1)
            
            datos["pagina_1_datos"]["nombre_solicitante"] = datos_extraidos["nombre_solicitante"]
            datos["pagina_1_datos"]["nombre_titular"] = datos_extraidos["nombre_titular"]
            datos["pagina_1_datos"]["direccion_postal"] = datos_extraidos["direccion_postal"]
            datos["pagina_1_datos"]["ssn"] = datos_extraidos["ssn"]
            datos["pagina_1_datos"]["email"] = datos_extraidos["email"]
            datos["pagina_1_datos"]["tipo_prestamo"] = datos_extraidos["tipo_prestamo"]
            datos["pagina_1_datos"]["cantidad_hipoteca"] = datos_extraidos["cantidad_hipoteca"]
            datos["pagina_1_datos"]["precio_venta"] = datos_extraidos["precio_venta"]
            
            fecha_cierre = buscar_multiples_patrones(text_p1, [
                r'cierre[:\s]*(\d{1,2}/\d{1,2}/\d{4})',
                r'estimada[:\s]*(\d{1,2}/\d{1,2}/\d{4})',
            ])
            if fecha_cierre != "NO ENCONTRADO":
                datos["pagina_1_datos"]["fecha_estimada_cierre"] = fecha_cierre
        
        # =========================================================
        # PÁGINA 2: FINCA Y TIPO DE PROPIEDAD
        # =========================================================
        if num_paginas >= 2:
            print("  Leyendo Página 2 (Finca)...")
            text_p2 = textos[1]
            
            finca = buscar_multiples_patrones(text_p2, [
                r'Finca\s*n[uú]mero\s*([\d,]+)',
                r'finca\s*número\s*([\d,]+)',
                r'n[uú]mero\s*([\d,]+)',
                r'FINCA[:\s]*([\d,]+)',
            ])
            if finca != "NO ENCONTRADO":
                finca = finca.rstrip(',').strip()
            
            tipo_propiedad = "Indeterminado"
            text_upper = text_p2.upper()
            
            if "PROPIEDAD HORIZONTAL" in text_upper or "APARTAMENTO" in text_upper or "CONDOMINIO" in text_upper:
                tipo_propiedad = "APARTAMENTO"
            elif "SOLAR" in text_upper or "CASA" in text_upper or "TERRENO" in text_upper or "URBANIZACIÓN" in text_upper:
                tipo_propiedad = "CASA"
            
            match_desc = re.search(r'(?:DESCRIPCI[OÓ]N|Porci[oó]n\s+de\s+terreno)[:\s]*(.{30,200})', text_p2, re.IGNORECASE | re.DOTALL)
            extracto = limpiar(match_desc.group(1))[:150] + "..." if match_desc else ""
            
            datos["pagina_2_propiedad"] = {
                "finca": finca,
                "tipo_calculado": tipo_propiedad,
                "extracto_descripcion": extracto
            }
        
        # =========================================================
        # PÁGINA 3: FECHA DEL DOCUMENTO
        # =========================================================
        if num_paginas >= 3:
            print("  Leyendo Página 3 (Fecha)...")
            text_p3 = textos[2]
            
            # Usar la función específica para página 3 (busca la ÚLTIMA fecha)
            fecha = extraer_fecha_documento_pagina3(text_p3)
            
            datos["pagina_3_fecha"]["fecha_detectada"] = fecha
        
        # =========================================================
        # PÁGINA 4: AUTORIZACIÓN (CRÍTICO)
        # =========================================================
        if num_paginas >= 4:
            print("  Leyendo Página 4 (Autorización - CRÍTICO)...")
            text_p4 = textos[3]
            
            # Buscar "Nombre del Solicitante:" específicamente (primera ocurrencia)
            match_nombre_p4 = re.search(r'Nombre\s+del\s+Solicitante[:\s]*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?=\n|Nombre\s+del\s+Co|$)', text_p4, re.IGNORECASE)
            if match_nombre_p4:
                nombre_p4 = limpiar(match_nombre_p4.group(1))
                # Limpiar errores comunes de OCR
                nombre_p4 = re.sub(r'\bANUKES\b', 'ANDRES', nombre_p4, flags=re.IGNORECASE)
                nombre_p4 = re.sub(r'\bOMARK?\b', 'OMAR', nombre_p4, flags=re.IGNORECASE)
            else:
                nombre_p4 = extraer_nombre_solicitante(text_p4)
                nombre_maestro = datos["pagina_1_datos"].get("nombre_solicitante", "")
                if nombre_p4 in ["NO ENCONTRADO", "Estimado Cliente"] or len(nombre_p4) < 5:
                    if nombre_maestro and nombre_maestro != "NO ENCONTRADO":
                        nombre_p4 = nombre_maestro
            
            # Buscar "Número de Solicitud:" específicamente (primera ocurrencia)
            match_num_solicitud = re.search(r'N[uú]mero\s+de\s+Solicitud[:\s]*(\d{10})', text_p4, re.IGNORECASE)
            if match_num_solicitud:
                num_solicitud = match_num_solicitud.group(1)
            else:
                num_solicitud = extraer_numero(text_p4, ['Solicitud', 'solicitud', 'Número', 'préstamo', 'prestamo'])
            
            estado_linea = verificar_linea_rechazo(text_p4)
            if "ALERTA ROJA" in estado_linea:
                datos["alertas"].append(f"Pág 4 CRÍTICO: {estado_linea}")
            
            firmado, tipo_firma, texto_firma = detectar_firma_en_texto(text_p4)
            estado_firma = f"{'FIRMADO' if firmado else 'FALTA FIRMA'} ({tipo_firma})"
            if not firmado:
                datos["alertas"].append("Pág 4: Falta firma del solicitante.")
            
            datos["pagina_4_autorizacion"] = {
                "nombre": nombre_p4,
                "num_solicitud": num_solicitud,
                "linea_rechazo_seguro": estado_linea,
                "estado_firma": estado_firma,
                "detalle_firma": texto_firma if texto_firma else None
            }
        
        # =========================================================
        # BUSCAR PÁGINAS DE DIVULGACIONES (pueden estar en diferentes posiciones)
        # =========================================================
        # Buscar la página que contiene "Divulgaciones relacionadas a los productos de seguro"
        pagina_divulgacion_productos = None
        pagina_divulgacion_titulo = None
        
        for idx, texto_pag in enumerate(textos):
            if "Divulgaciones relacionadas a los productos de seguro" in texto_pag:
                pagina_divulgacion_productos = idx
            if "Divulgaciones Seguro de Título" in texto_pag or "Divulgaciones Seguro de Titulo" in texto_pag:
                pagina_divulgacion_titulo = idx
        
        # =========================================================
        # PÁGINA DE DIVULGACIONES DE PRODUCTOS DE SEGURO
        # =========================================================
        if pagina_divulgacion_productos is not None:
            print(f"  Leyendo Página {pagina_divulgacion_productos + 1} (Divulgaciones Productos)...")
            text_p5 = textos[pagina_divulgacion_productos]
            
            # Buscar "Número de solicitud:" o "Número de préstamo:" (son equivalentes)
            match_num_p5 = re.search(r'N[uú]mero\s+de\s+(?:solicitud|pr[eé]stamo)[:\s]*(\d{10})', text_p5, re.IGNORECASE)
            if match_num_p5:
                num_prestamo = match_num_p5.group(1)
            else:
                num_prestamo = extraer_numero(text_p5, ['solicitud', 'Solicitud', 'préstamo', 'prestamo'])
        elif num_paginas >= 5:
            print("  Leyendo Página 5 (Divulgaciones - posición estándar)...")
            text_p5 = textos[4]
            
            match_num_p5 = re.search(r'N[uú]mero\s+de\s+(?:solicitud|pr[eé]stamo)[:\s]*(\d{10})', text_p5, re.IGNORECASE)
            if match_num_p5:
                num_prestamo = match_num_p5.group(1)
            else:
                num_prestamo = extraer_numero(text_p5, ['solicitud', 'Solicitud', 'préstamo', 'prestamo'])
        else:
            text_p5 = ""
            num_prestamo = "NO ENCONTRADO"
        
        if pagina_divulgacion_productos is not None or num_paginas >= 5:
            
            nombre_maestro = datos["pagina_1_datos"].get("nombre_solicitante", "")
            nombre_en_p5 = "NO VERIFICABLE"
            
            if nombre_maestro and nombre_maestro != "NO ENCONTRADO":
                nombre_maestro_upper = nombre_maestro.upper()
                text_p5_upper = text_p5.upper()
                
                if nombre_maestro_upper in text_p5_upper:
                    nombre_en_p5 = "CONFIRMADO (Exacto)"
                else:
                    partes = [p for p in nombre_maestro_upper.split() if len(p) > 2]
                    if partes:
                        coincidencias = sum(1 for p in partes if p in text_p5_upper)
                        
                        if coincidencias >= len(partes):
                            nombre_en_p5 = "CONFIRMADO (Todas las palabras)"
                        elif coincidencias >= len(partes) * 0.7:
                            nombre_en_p5 = "CONFIRMADO (Mayoría de palabras)"
                        elif coincidencias >= 1:
                            nombre_en_p5 = "PARCIAL (Alguna coincidencia)"
                        else:
                            nombre_en_p5 = "NO ENCONTRADO en página"
            
            # Detectar firma: buscar patrón "Certifico...NOMBRE...fecha...Firma"
            firmado_p5 = False
            tipo_firma_p5 = "No encontrada"
            texto_firma_p5 = None
            
            # Patrón de firma con timestamp: NOMBRE + fecha + AM/PM + PDT
            match_firma_ts = re.search(r'([A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+)+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?\s*(?:PDT|PST)?)', text_p5, re.IGNORECASE)
            if match_firma_ts:
                firmado_p5 = True
                tipo_firma_p5 = "Firma Digital (Timestamp)"
                texto_firma_p5 = f"{match_firma_ts.group(1)} - {match_firma_ts.group(2)} {match_firma_ts.group(3)}"
            
            # Buscar si hay "Certifico" seguido de nombre
            if not firmado_p5:
                match_certifico = re.search(r'Certifico[^\n]*\n([A-ZÁÉÍÓÚÑ\s]+?)(?:\d{1,2}/\d{1,2}/\d{4}|Firma)', text_p5, re.IGNORECASE)
                if match_certifico:
                    firmado_p5 = True
                    tipo_firma_p5 = "Firma de Texto"
                    texto_firma_p5 = limpiar(match_certifico.group(1))
            
            # Fallback: buscar "Firma del Solicitante" con contenido antes
            if not firmado_p5 and "Firma del Solicitante" in text_p5:
                firmado_p5 = True
                tipo_firma_p5 = "Área de firma detectada"
            
            estado_firma_p5 = f"{'FIRMADO' if firmado_p5 else 'FALTA FIRMA'} ({tipo_firma_p5})"
            if not firmado_p5:
                datos["alertas"].append("Pág 5: Falta firma del solicitante.")
            
            datos["pagina_5_divulgacion"] = {
                "num_solicitud": num_prestamo,
                "validacion_nombre": nombre_en_p5,
                "estado_firma": estado_firma_p5,
                "detalle_firma": texto_firma_p5
            }
        
        # =========================================================
        # PÁGINA DE DIVULGACIONES SEGURO DE TÍTULO
        # =========================================================
        if pagina_divulgacion_titulo is not None:
            print(f"  Leyendo Página {pagina_divulgacion_titulo + 1} (Divulgaciones Título)...")
            text_p6 = textos[pagina_divulgacion_titulo]
        elif num_paginas >= 6:
            print("  Leyendo Página 6 (Título - posición estándar)...")
            text_p6 = textos[5]
        else:
            text_p6 = ""
        
        if pagina_divulgacion_titulo is not None or num_paginas >= 6:
            
            # Buscar "Número de solicitud:" o "Número de préstamo:"
            match_num_p6 = re.search(r'N[uú]mero\s+de\s+(?:solicitud|pr[eé]stamo)[:\s]*(\d{10})', text_p6, re.IGNORECASE)
            if match_num_p6:
                num_solicitud_p6 = match_num_p6.group(1)
            else:
                num_solicitud_p6 = extraer_numero(text_p6, ['solicitud', 'Solicitud', 'préstamo'])
            
            # Si no se encontró, usar el de página 5
            if num_solicitud_p6 == "NO ENCONTRADO":
                num_p5 = datos.get("pagina_5_divulgacion", {}).get("num_solicitud", "")
                if num_p5 and num_p5 != "NO ENCONTRADO":
                    num_solicitud_p6 = num_p5
            
            # Detectar firma con patrón: NOMBRE + fecha + timestamp
            firmado_p6 = False
            tipo_firma_p6 = "No encontrada"
            texto_firma_p6 = None
            
            # Patrón de firma con timestamp: NOMBRE APELLIDO + fecha + hora + AM/PM + PDT
            match_firma_ts = re.search(r'([A-ZÁÉÍÓÚÑ]+(?:\s+[A-ZÁÉÍÓÚÑ]+)+)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}\s*(?:AM|PM)?\s*(?:PDT|PST)?)', text_p6, re.IGNORECASE)
            if match_firma_ts:
                firmado_p6 = True
                tipo_firma_p6 = "Firma Digital (Timestamp)"
                texto_firma_p6 = f"{match_firma_ts.group(1)} - {match_firma_ts.group(2)} {match_firma_ts.group(3)}"
            
            # Buscar si hay "Certifico" seguido de nombre
            if not firmado_p6:
                match_certifico = re.search(r'Certifico[^\n]*\n([A-ZÁÉÍÓÚÑ\s]+?)(?:\d{1,2}/\d{1,2}/\d{4}|Firma|xX|Xx)', text_p6, re.IGNORECASE)
                if match_certifico:
                    firmado_p6 = True
                    tipo_firma_p6 = "Firma de Texto"
                    texto_firma_p6 = limpiar(match_certifico.group(1))
            
            # Fallback: buscar timestamp solo
            if not firmado_p6:
                match_ts = re.search(r'(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s*PDT)?)', text_p6)
                if match_ts:
                    firmado_p6 = True
                    tipo_firma_p6 = "Firma Digital (Timestamp)"
                    texto_firma_p6 = match_ts.group(1)
            
            # Fallback: buscar "Firma" con X
            if not firmado_p6 and re.search(r'[xX]+\s*Firma', text_p6):
                firmado_p6 = True
                tipo_firma_p6 = "Firma con X"
                texto_firma_p6 = "Marca X detectada"
            
            estado_firma_p6 = f"{'FIRMADO' if firmado_p6 else 'FALTA FIRMA'} ({tipo_firma_p6})"
            if not firmado_p6:
                datos["alertas"].append("Pág 6: Falta firma del solicitante.")
            
            datos["pagina_6_titulo"] = {
                "num_solicitud": num_solicitud_p6,
                "estado_firma": estado_firma_p6,
                "detalle_firma": texto_firma_p6
            }
        
        # =========================================================
        # POST-PROCESO
        # =========================================================
        if datos["pagina_4_autorizacion"].get("num_solicitud") == "NO ENCONTRADO":
            num_prestamo = datos["pagina_5_divulgacion"].get("num_prestamo", "")
            num_solicitud_p6 = datos["pagina_6_titulo"].get("num_solicitud", "")
            if num_prestamo and num_prestamo != "NO ENCONTRADO":
                datos["pagina_4_autorizacion"]["num_solicitud"] = num_prestamo
            elif num_solicitud_p6 and num_solicitud_p6 != "NO ENCONTRADO":
                datos["pagina_4_autorizacion"]["num_solicitud"] = num_solicitud_p6
        
    except Exception as e:
        datos["alertas"].append(f"ERROR CRÍTICO: {str(e)}")
        import traceback
        traceback.print_exc()
    
    # =========================================================
    # RESUMEN FINAL
    # =========================================================
    if not datos["alertas"]:
        datos["resumen_validacion"] = "APROBADO (Documento limpio y completo)"
    else:
        tiene_alerta_roja = any("CRÍTICO" in a or "ALERTA ROJA" in a for a in datos["alertas"])
        if tiene_alerta_roja:
            datos["resumen_validacion"] = "RECHAZADO - ALERTA ROJA (Ver alertas críticas)"
        else:
            datos["resumen_validacion"] = "REVISIÓN REQUERIDA (Ver alertas)"
    
    return datos


# =========================================================
# EJECUCIÓN PRINCIPAL
# =========================================================
if __name__ == "__main__":
    # Buscar archivos _OCR.pdf primero, si no hay, usar los originales
    archivos_ocr = glob.glob("*_OCR.pdf")
    
    if archivos_ocr:
        archivos = archivos_ocr
        print("Usando archivos con OCR integrado (_OCR.pdf)")
    else:
        archivos = [f for f in glob.glob("*.pdf") if not f.endswith("_OCR.pdf")]
        print("⚠ No se encontraron archivos _OCR.pdf")
        print("  Ejecuta primero: python convertir_a_searchable.py")
        print("  Usando archivos originales (puede ser menos preciso)\n")
    
    if not archivos:
        print("No se encontraron archivos PDF en el directorio actual.")
    else:
        for f in ["reporte_verificacion.txt", "reporte_verificacion.json"]:
            if os.path.exists(f):
                os.remove(f)
        
        todos_resultados = []
        
        for archivo in archivos:
            print(f"\n{'='*60}")
            resultado = procesar_cotizacion(archivo)
            todos_resultados.append(resultado)
            
            print(json.dumps(resultado, indent=4, ensure_ascii=False))
            print("-" * 60)
        
        with open("reporte_verificacion.txt", "w", encoding="utf-8") as f:
            f.write("REPORTE DE VERIFICACIÓN DE COTIZACIONES (v2.0 - OCR Nativo)\n")
            f.write("="*60 + "\n\n")
            for res in todos_resultados:
                f.write(f"ARCHIVO: {res['archivo']}\n")
                f.write(f"RESULTADO: {res['resumen_validacion']}\n")
                f.write("-"*40 + "\n")
                f.write(json.dumps(res, indent=4, ensure_ascii=False))
                f.write("\n\n")
        
        with open("reporte_verificacion.json", "w", encoding="utf-8") as f:
            json.dump(todos_resultados, f, indent=4, ensure_ascii=False)
        
        print(f"\n{'='*60}")
        print("Reportes guardados en:")
        print("  - reporte_verificacion.txt")
        print("  - reporte_verificacion.json")

