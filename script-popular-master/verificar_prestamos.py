import fitz  # PyMuPDF
import pytesseract
from PIL import Image, ImageEnhance
import re
import json
import glob
import os
import io
import difflib  # Para comparación difusa de nombres

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

def pdf_pagina_a_texto(doc, num_pagina, zoom=2):
    """Convierte una página de PDF a imagen y extrae texto con OCR."""
    page = doc.load_page(num_pagina)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img_data = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_data))
    
    try:
        texto = pytesseract.image_to_string(img, lang='spa')
    except:
        texto = pytesseract.image_to_string(img)
    
    return texto

def pdf_pagina_a_texto_detallado(doc, num_pagina, zoom=4):
    """
    Extrae texto con OCR usando múltiples configuraciones para capturar todo.
    Combina PSM 6 (bloque) y PSM 11 (sparse) para mejores resultados en tablas.
    """
    from PIL import ImageEnhance
    
    page = doc.load_page(num_pagina)
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    img_data = pix.tobytes("png")
    img = Image.open(io.BytesIO(img_data))
    
    # Mejorar contraste
    enhancer = ImageEnhance.Contrast(img)
    img_enhanced = enhancer.enhance(1.5)
    
    textos = []
    
    try:
        # Método 1: OCR estándar (PSM 6) con contraste
        texto_bloque = pytesseract.image_to_string(img_enhanced, lang='spa', config='--psm 6')
        textos.append(texto_bloque)
        
        # Método 2: OCR sparse (PSM 11) con contraste
        texto_sparse = pytesseract.image_to_string(img_enhanced, lang='spa', config='--psm 11')
        textos.append(texto_sparse)
        
        # Método 3: OCR sparse (PSM 11) SIN CONTRASTE (Raw) - Para documentos claros que el contraste daña
        texto_raw_sparse = pytesseract.image_to_string(img, lang='spa', config='--psm 11')
        textos.append(texto_raw_sparse)
        
        # Método 4: image_to_data para reconstrucción por posición (usando imagen mejorada)
        data = pytesseract.image_to_data(img_enhanced, lang='spa', output_type=pytesseract.Output.DATAFRAME)
        data = data[data.conf > 0]
        
        lines = {}
        for idx, row in data.iterrows():
            if not row['text'] or not str(row['text']).strip():
                continue
            y_rounded = (row['top'] // 40) * 40
            if y_rounded not in lines:
                lines[y_rounded] = []
            lines[y_rounded].append((row['left'], str(row['text'])))
        
        texto_lineas = []
        for y in sorted(lines.keys()):
            words = lines[y]
            words.sort(key=lambda x: x[0])
            line_text = ' '.join([w[1] for w in words])
            texto_lineas.append(line_text)
        
        textos.append('\n'.join(texto_lineas))
        
        # Combinar todos los textos (el analizador buscará en todos)
        return '\n---\n'.join(textos)
        
    except Exception as e:
        try:
            return pytesseract.image_to_string(img, lang='spa')
        except:
            return pytesseract.image_to_string(img)

def limpiar_texto_ocr(texto):
    """
    Reconstruye líneas rotas por columnas de tabla.
    Intenta unir líneas que parecen continuar la anterior.
    """
    if not texto: 
        return ""
    
    # 1. Eliminar comillas y caracteres de formato CSV que a veces mete Tesseract
    texto = texto.replace('","', '\n').replace('"', '')
    
    # 2. Unificar líneas rotas arbitrariamente
    lineas = texto.split('\n')
    texto_reconstruido = []
    
    etiquetas_comunes = ["Nombre", "Dirección", "Número", "Cantidad", "Precio", 
                         "Tipo", "Fecha", "Correo", "Seguro", "Email", "SSN"]
    
    buffer = ""
    for linea in lineas:
        linea = linea.strip()
        if not linea: 
            continue
        
        # Si la línea empieza con una etiqueta conocida, es una nueva entrada
        es_etiqueta = any(linea.startswith(tag) for tag in etiquetas_comunes)
        
        if es_etiqueta:
            if buffer: 
                texto_reconstruido.append(buffer)
            buffer = linea
        else:
            # Si no es etiqueta, probablemente es la continuación del valor anterior
            buffer += " " + linea
            
    if buffer: 
        texto_reconstruido.append(buffer)
    
    return "\n".join(texto_reconstruido)

def extraer_pares_clave_valor(texto):
    """
    Estrategia de extracción directa del texto OCR fragmentado.
    Busca patrones específicos en todo el texto sin depender de estructura.
    """
    datos = {}
    texto_todo = texto.replace('\n', ' ')  # Unir todo en una línea
    
    # --- NOMBRE SOLICITANTE ---
    # Buscar patrón: palabras en mayúsculas que parecen nombres (2-4 palabras)
    # Excluir palabras que son claramente no-nombres
    palabras_excluidas = ['POPULAR', 'MORTGAGE', 'INSURANCE', 'BANCO', 'PUERTO', 'RICO', 
                          'TITULO', 'PÓLIZA', 'COTIZACIÓN', 'SOLICITUD', 'CAPITAL', 
                          'TITLE', 'SERVICES', 'AREA', 'PROCESO', 'CALLE', 'PANORAMA',
                          'TERRAZAS', 'CARRAIZO', 'FÍSICA', 'POSTAL', 'TRINIDAD']
    
    # Buscar apellidos comunes para anclar la búsqueda
    apellidos = ['GONZALEZ', 'RODRIGUEZ', 'MARTINEZ', 'LOPEZ', 'GARCIA', 'HERNANDEZ', 
                 'PEREZ', 'SANCHEZ', 'RAMIREZ', 'TORRES', 'RIVERA', 'AROCHO', 'ORTIZ']
    
    nombre = "NO ENCONTRADO"
    for apellido in apellidos:
        # Buscar NOMBRE SEGUNDO_NOMBRE APELLIDO o NOMBRE APELLIDO1 APELLIDO2
        patron = rf'([A-ZÁÉÍÓÚÑ]{{3,}}\s+(?:[A-ZÁÉÍÓÚÑ]{{2,}}\s+)?(?:[A-ZÁÉÍÓÚÑ]{{2,}}\s+)?{apellido})'
        match = re.search(patron, texto)
        if match:
            candidato = limpiar(match.group(1))
            if candidato and not any(exc in candidato for exc in palabras_excluidas):
                nombre = candidato
                break
    datos["nombre_solicitante"] = nombre
    
    # --- NOMBRE TITULAR (usar mismo que solicitante si no se encuentra) ---
    datos["nombre_titular"] = nombre
    
    # --- SSN ---
    # OCR puede leer mal algunos caracteres (7 como /, etc.)
    patrones_ssn = [
        r'(\d{3}-\d{2}-\d{4})',  # Formato estándar
        r'(\d{3}[-/]\d{2}[-/]\d{4})',  # Con / en lugar de -
        r'(\d{3}\s*[-/]\s*\d{2}\s*[-/]\s*\d{4})',  # Con espacios
    ]
    ssn_encontrado = None
    for patron in patrones_ssn:
        match_ssn = re.search(patron, texto)
        if match_ssn:
            ssn = match_ssn.group(1)
            # Normalizar: reemplazar / por - y eliminar espacios
            ssn = ssn.replace('/', '-').replace(' ', '')
            ssn_encontrado = ssn
            break
    datos["ssn"] = ssn_encontrado if ssn_encontrado else "NO ENCONTRADO"
    
    # --- EMAIL ---
    # OCR puede omitir @ o leerlo como O, 0, o pegarlo con texto anterior
    patrones_email = [
        r'([\w\.\-]+@[\w\.\-]+\.com)',  # Formato estándar
        r'([\w\.\-]+[O0]gmail\.com)',    # O o 0 en lugar de @
        r'([\w]+gmail\.com)',            # Pegado sin @
        r'(\d*[a-z]+[a-z0-9]*gmail\.com)',  # Número + letras + gmail
    ]
    
    email_encontrado = None
    for patron in patrones_email:
        match_email = re.search(patron, texto, re.IGNORECASE)
        if match_email:
            email = match_email.group(1)
            # Insertar @ si falta
            if '@' not in email:
                # Buscar donde insertar el @
                if 'gmail' in email.lower():
                    email = re.sub(r'([a-z0-9])gmail', r'\1@gmail', email, flags=re.IGNORECASE)
                elif 'yahoo' in email.lower():
                    email = re.sub(r'([a-z0-9])yahoo', r'\1@yahoo', email, flags=re.IGNORECASE)
                elif 'hotmail' in email.lower():
                    email = re.sub(r'([a-z0-9])hotmail', r'\1@hotmail', email, flags=re.IGNORECASE)
            # También manejar O y 0 como @
            email = re.sub(r'([a-z0-9])O(gmail|yahoo|hotmail)', r'\1@\2', email, flags=re.IGNORECASE)
            email = re.sub(r'([a-z0-9])0(gmail|yahoo|hotmail)', r'\1@\2', email, flags=re.IGNORECASE)
            email_encontrado = email.lower()
            break
    
    datos["email"] = email_encontrado if email_encontrado else "NO ENCONTRADO"
    
    # --- DIRECCIÓN ---
    # Buscar patrones de dirección de PR (Español e Inglés)
    patrones_dir = [
        # Patrón 1: P O BOX
        r'Postal[:\s]*(P\s*O\s*BOX\s+\d+[^|]+?(?:PR\s*\d{5}|00\d{3})[^|\n]*)',
        # Patrón 2: Después de "Postal:" con tipos de vía
        r'Postal[:\s]+(\d*\s*(?:TERRAZAS|URB|COND|CALLE)[^|]+?(?:San Juan|Trujillo|Bayamon|Carolina|PR)[^|\n]*)',
        # Patrón 3: Número + tipo de vía + ciudad (Lista ampliada)
        r'(\d+\s+(?:TERRAZAS|URB|COND|CALLE|AVE|BO|BARRIO)[^|]+(?:San Juan|Trujillo|Alto|Bayamon|Carolina|Ponce|Caguas|Guaynabo|Mayaguez|Arecibo|PR\s*\d{5}|00\d{3})[^|]*)',
        # Patrón 4: TERRAZAS DE CARRAIZO como ancla
        r'((?:\d+\s+)?TERRAZAS\s+DE\s+CARRAIZO[^|]*(?:San Juan|PR|00\d{3})[^|]*)',
        # Patrón 5: P O BOX genérico
        r'(P\s*O\s*BOX\s+\d+[^|]+00\d{3})',
        # Nuevos patrones para formularios en inglés o formatos estándar
        r'(?:Property\s+Address|Direcci[oó]n\s+Propiedad)[:\s]*([^|\n]+(?:PR|Puerto Rico)\s+00\d{3})',
        r'(?:Address|Direcci[oó]n)[:\s]*(\d+\s+[A-Za-z\s]+(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Calle|Avenida)[^|\n]+(?:PR|Puerto Rico)\s+00\d{3})',
        # Patrón tolerante a OCR para Dirección Física
        r'[A-Za-z]*recci[oó]n\s+F[íi]sica[:\s]*(.+?(?:PR|PRO|Puerto Rico)[^0-9]*[O0]?\d{3,5})',
        # Patrón genérico final: algo que termina en PR 00XXX o PRO0XXX
        r'([A-Za-z0-9\s\.,]+(?:PR|PRO)\s*[O0]?\d{3,5})',
    ]
    
    direccion_encontrada = None
    for patron in patrones_dir:
        # Usar re.DOTALL para que el punto coincida con saltos de línea
        match_dir = re.search(patron, texto, re.IGNORECASE | re.DOTALL)
        if match_dir:
            direccion = limpiar(match_dir.group(1))
            # Limpiar caracteres extraños
            direccion = re.sub(r'[\|(){}\[\]]', '', direccion)
            direccion = re.sub(r'\s+', ' ', direccion)
            if direccion and len(direccion) > 10:
                direccion_encontrada = direccion
                break
    
    datos["direccion_postal"] = direccion_encontrada if direccion_encontrada else "NO ENCONTRADO"
    
    # --- TIPO DE PRÉSTAMO ---
    match_tipo = re.search(r'(Non\s+Conf\s*\([^)]+\))', texto, re.IGNORECASE)
    if match_tipo:
        datos["tipo_prestamo"] = limpiar(match_tipo.group(1))
    else:
        # Usar \b para evitar coincidencias parciales (ej. "Nueva" -> "va")
        match_tipo2 = re.search(r'\b(FHA|VA|Conventional|USDA|Rural\s+Prime\s+Fixed\s+30|Rural\s+Prime)\b', texto, re.IGNORECASE)
        datos["tipo_prestamo"] = match_tipo2.group(1) if match_tipo2 else "NO ENCONTRADO"
    
    # --- HIPOTECA Y PRECIO DE VENTA ---
    # Estrategia: buscar primero con etiquetas y formato completo
    
    # Buscar formato con $ y decimales (incluyendo variantes de OCR)
    patrones_hipoteca = [
        r'Hipoteca[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'Cantidad\s+de\s+la\s+Hipoteca[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'(?:Loan|Mortgage|Principal)\s+Amount[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'Base\s+Loan\s+Amount[:\s]*\$?\s*([\d,]+\.\d{2})',
        r'Total\s+Loan\s+Amount[:\s]*\$?\s*([\d,]+\.\d{2})',
    ]
    patrones_precio = [
        r'Precio\s+de\s+Venta[:\s]*\$?\s*([\d,\s]+\.\d{2})',  # Permite espacios
        r'Venta[:\s]*\$?\s*([\d,\s]+\.\d{2})',
        r'\(?PARANA\s*([\d,]+\.\d{2})',  # OCR a veces lee "Precio" como "(PARANA"
        r'Precio[:\s]*\$?\s*([\d,\s]+\.\d{2})',
        r'(?:Purchase|Sales|Contract)\s+Price[:\s]*\$?\s*([\d,\s]+\.\d{2})',
        r'Price[:\s]*\$?\s*([\d,\s]+\.\d{2})',
    ]
    
    hipoteca = None
    precio = None
    
    # Buscar hipoteca con etiqueta
    for patron in patrones_hipoteca:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            valor = match.group(1).replace(',', '')
            hipoteca = f"${float(valor):,.2f}"
            break
    
    # Buscar precio con etiqueta
    for patron in patrones_precio:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            valor = match.group(1).replace(',', '').replace(' ', '')  # Quitar comas y espacios
            try:
                precio = f"${float(valor):,.2f}"
                break
            except:
                continue
    
    # SIEMPRE buscar todos los números con formato de precio para complementar
    # Buscar todos los números con formato $XXX,XXX.XX o XXX,XXX.XX (o sin decimales si son grandes)
    precios_encontrados = re.findall(r'\$?\s*([\d,]+(?:\.\d{2})?)', texto)
    valores = []
    for p in precios_encontrados:
        try:
            # Limpiar y validar
            val_str = p.replace(',', '').replace('$', '').strip()
            # Si termina en punto, quitarlo
            if val_str.endswith('.'): val_str = val_str[:-1]
            
            val = float(val_str)
            
            # Rango razonable para hipotecas/precios de PR: $20k a $10M
            if 20000 <= val <= 10000000:
                valores.append(val)
        except:
            pass
    
    # Eliminar duplicados y ordenar
    valores = sorted(set(valores))
    
    # Si encontramos al menos 2 valores diferentes, usar el mayor como precio
    if len(valores) >= 2:
        if not hipoteca:
            hipoteca = f"${valores[0]:,.2f}"
        if not precio:
            precio = f"${valores[-1]:,.2f}"
        # Si ya tenemos hipoteca pero no precio, y hay un valor mayor
        elif hipoteca and not precio:
            valor_hip = float(hipoteca.replace('$', '').replace(',', ''))
            for v in reversed(valores):
                if v > valor_hip:
                    precio = f"${v:,.2f}"
                    break
    elif len(valores) == 1:
        if hipoteca and not precio:
            # Verificar si el valor es diferente a la hipoteca
            valor_hip = float(hipoteca.replace('$', '').replace(',', ''))
            if abs(valores[0] - valor_hip) > 100:  # Son significativamente diferentes
                precio = f"${valores[0]:,.2f}"
        elif not hipoteca and precio:
            hipoteca = f"${valores[0]:,.2f}"
        elif not hipoteca and not precio:
            precio = f"${valores[0]:,.2f}"
    
    # Si aún no encontramos, buscar números sin formato (como fallback)
    if not hipoteca or not precio:
        numeros = re.findall(r'\b(\d{6,8})\b', texto)
        for num in numeros:
            valor = int(num)
            if 10000000 <= valor <= 999999999:  # Parece tener decimales implícitos
                valor_real = valor / 100
                if 50000 <= valor_real <= 500000:
                    if not hipoteca:
                        hipoteca = f"${valor_real:,.2f}"
                    elif not precio:
                        precio = f"${valor_real:,.2f}"
    
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
    """Extrae el nombre del solicitante del texto OCR."""
    texto_limpio = limpiar_texto_ocr(texto)
    
    # Primero intentar con etiquetas
    patrones = [
        r"Nombre\s+del\s+Solicitante[:\s\.]*([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]+?)(?=\n|Cantidad|Nombre del Co|$)",
        r"Solicitante[:\s\.]+([A-ZÁÉÍÓÚÑ][A-Za-záéíóúñÁÉÍÓÚÑ\s]{5,})",
    ]
    
    for patron in patrones:
        match = re.search(patron, texto_limpio, re.IGNORECASE)
        if match:
            nombre = limpiar(match.group(1))
            if nombre and len(nombre) > 5:
                return nombre
    
    # Buscar patrones de nombres latinos en mayúsculas (2-4 palabras)
    matches = re.findall(r'([A-ZÁÉÍÓÚÑ]{3,}\s+(?:[A-ZÁÉÍÓÚÑ]{2,}\s+){1,3}[A-ZÁÉÍÓÚÑ]{3,})', texto)
    
    # Filtrar resultados que son claramente no-nombres
    palabras_excluidas = ['POPULAR', 'MORTGAGE', 'INSURANCE', 'BANCO', 'PUERTO', 'RICO', 
                          'TITULO', 'PÓLIZA', 'COTIZACIÓN', 'SOLICITUD', 'CAPITAL', 
                          'TITLE', 'SERVICES', 'AREA', 'PROCESO', 'CALLE', 'PANORAMA',
                          'TERRAZAS', 'CARRAIZO']
    
    for m in matches:
        if not any(exc in m for exc in palabras_excluidas):
            palabras = [p for p in m.split() if len(p) >= 3]
            if len(palabras) >= 2:
                return limpiar(m)
    
    # Fallback: buscar apellidos comunes
    apellidos = ['GONZALEZ', 'RODRIGUEZ', 'MARTINEZ', 'LOPEZ', 'GARCIA', 'HERNANDEZ', 
                 'PEREZ', 'SANCHEZ', 'RAMIREZ', 'TORRES', 'RIVERA', 'AROCHO', 'ORTIZ']
    
    for apellido in apellidos:
        patron = rf'([A-ZÁÉÍÓÚÑ]+\s+(?:[A-ZÁÉÍÓÚÑ]+\s+)?{apellido})'
        match = re.search(patron, texto)
        if match:
            nombre = limpiar(match.group(1))
            # Verificar que no sea parte de dirección
            if not any(exc in nombre for exc in palabras_excluidas):
                return nombre
    
    return "NO ENCONTRADO"

def extraer_email(texto):
    """Busca cualquier email en el texto (tolera OCR)."""
    patrones = [
        r'([\w\.\-]+@[\w\.\-]+\.[a-z]{2,})',
        r'([\w\.\-]+[O0]gmail\.com)',
        r'([\w\.\-]+[@O0][\w\.\-]+\.com)',
    ]
    
    for patron in patrones:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            email = match.group(1)
            email = re.sub(r'([a-z0-9])O(gmail|yahoo|hotmail|outlook)', r'\1@\2', email, flags=re.IGNORECASE)
            email = re.sub(r'([a-z0-9])0(gmail|yahoo|hotmail|outlook)', r'\1@\2', email, flags=re.IGNORECASE)
            # Validar que parece email real
            if '@' in email or 'gmail' in email.lower():
                return email
    return "NO ENCONTRADO"

def extraer_ssn(texto):
    """Busca SSN en formato XXX-XX-XXXX."""
    match = re.search(r'(\d{3}[-\s]?\d{2}[-\s]?\d{4})', texto)
    return match.group(1) if match else "NO ENCONTRADO"

def extraer_precio(texto, palabras_clave):
    """Busca precio después de palabras clave o números sin formato."""
    texto_limpio = limpiar_texto_ocr(texto)
    
    # Primero intentar con formato estándar
    for palabra in palabras_clave:
        patrones = [
            rf'{palabra}[^:\n]*[:\s]*(\$[\d,]+\.\d{{2}})',
            rf'{palabra}[:\s]*(\$?\s*[\d,]+\.\d{{2}})',
        ]
        for patron in patrones:
            match = re.search(patron, texto_limpio, re.IGNORECASE)
            if match:
                precio = match.group(1).replace(' ', '')
                if not precio.startswith('$'):
                    precio = '$' + precio
                valor = re.sub(r'[^\d.]', '', precio)
                if valor and float(valor) > 1000:
                    return precio
    
    # Si no encuentra, buscar números sin formato
    numeros = re.findall(r'\b(\d{6,10})\b', texto)
    for num in numeros:
        valor = int(num)
        # Valores que parecen precios (entre $100,000 y $10,000,000)
        if 10000000 <= valor <= 1000000000:  # Sin decimales (125,000.00 -> 12500000)
            return f"${valor/100:,.2f}"
        elif 100000 <= valor <= 10000000:  # Con decimales perdidos
            return f"${valor:,.2f}"
    
    return "NO ENCONTRADO"

def extraer_direccion(texto):
    """Extrae dirección de Puerto Rico del texto OCR."""
    texto_limpio = limpiar_texto_ocr(texto)
    
    patrones = [
        r'Direcci[oó]n\s+Postal[:\s\.]*([^\n]+(?:PR|Puerto Rico|00\d{3})[^\n]*)',
        r'(\d+[^\n]*(?:TERRAZAS|URB|COND|CALLE|AVE)[^\n]*(?:PR|00\d{3})[^\n]*)',
        r'(\d+[^\n]+(?:San Juan|Trujillo|Bayamon|Carolina|Ponce|Caguas|Mayaguez)[^\n]*)',
    ]
    
    for patron in patrones:
        match = re.search(patron, texto_limpio, re.IGNORECASE)
        if match:
            direccion = limpiar(match.group(1))
            if direccion and len(direccion) > 10:
                return direccion
    
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
    
    return (True, "Posible firma (OCR no legible)", "")

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

def extraer_numero(texto, palabras_clave):
    """Extrae un número después de palabras clave."""
    # Primero buscar con formato estándar
    for palabra in palabras_clave:
        patron = rf'{palabra}[:\s#]*(\d{{7,12}})'
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            return match.group(1)
    
    # Buscar números largos que podrían estar fragmentados por OCR
    # Ejemplo: "Número de préstamo: 070" seguido de "3553842" en otra línea
    for palabra in palabras_clave:
        # Buscar la palabra clave y luego cualquier número cercano
        patron = rf'{palabra}[:\s#]*(\d{{3,}})'
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            num_inicio = match.group(1)
            # Buscar si hay más dígitos inmediatamente después
            pos_fin = match.end()
            texto_resto = texto[pos_fin:pos_fin+20]
            mas_digitos = re.search(r'^[\s\n]*(\d+)', texto_resto)
            if mas_digitos:
                return num_inicio + mas_digitos.group(1)
            elif len(num_inicio) >= 7:
                return num_inicio
    
    # Buscar cualquier número de 10 dígitos que empiece con 070 (formato de préstamo Popular)
    match_070 = re.search(r'\b(070\d{7})\b', texto)
    if match_070:
        return match_070.group(1)
    
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
        doc = fitz.open(pdf_path)
        num_paginas = len(doc)
        print(f"  Páginas detectadas: {num_paginas}")
        
        # =========================================================
        # PÁGINA 1: DATOS MAESTROS (LÓGICA MEJORADA)
        # =========================================================
        if num_paginas >= 1:
            print("  Leyendo Página 1 (Datos Maestros)...")
            # Usar método detallado para tablas
            text_p1 = pdf_pagina_a_texto_detallado(doc, 0)
            
            # Usar la nueva función de extracción robusta
            datos_extraidos = extraer_pares_clave_valor(text_p1)
            
            datos["pagina_1_datos"]["nombre_solicitante"] = datos_extraidos["nombre_solicitante"]
            datos["pagina_1_datos"]["nombre_titular"] = datos_extraidos["nombre_titular"]
            datos["pagina_1_datos"]["direccion_postal"] = datos_extraidos["direccion_postal"]
            datos["pagina_1_datos"]["ssn"] = datos_extraidos["ssn"]
            datos["pagina_1_datos"]["email"] = datos_extraidos["email"]
            datos["pagina_1_datos"]["tipo_prestamo"] = datos_extraidos["tipo_prestamo"]
            datos["pagina_1_datos"]["cantidad_hipoteca"] = datos_extraidos["cantidad_hipoteca"]
            datos["pagina_1_datos"]["precio_venta"] = datos_extraidos["precio_venta"]
            
            # Fecha estimada de cierre (bonus)
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
            text_p2 = pdf_pagina_a_texto(doc, 1)
            
            finca = buscar_multiples_patrones(text_p2, [
                r'Finca\s*n[uú]mero\s*([\d,]+)',
                r'n[uú]mero\s*([\d,]+)',
                r'FINCA[:\s]*([\d,]+)',
            ])
            if finca != "NO ENCONTRADO":
                finca = finca.rstrip(',').strip()
            
            tipo_propiedad = "Indeterminado"
            text_upper = text_p2.upper()
            
            if "PROPIEDAD HORIZONTAL" in text_upper or "APARTAMENTO" in text_upper or "CONDOMINIO" in text_upper:
                tipo_propiedad = "APARTAMENTO"
            elif "SOLAR" in text_upper or "CASA" in text_upper or "TERRENO" in text_upper:
                tipo_propiedad = "CASA"
            
            match_desc = re.search(r'DESCRIPCI[OÓ]N[:\s]*(.{30,200})', text_p2, re.IGNORECASE | re.DOTALL)
            
            if not match_desc:
                # Intentar buscar patrones típicos de descripción legal si falta la etiqueta
                match_desc = re.search(r'(?:URBAN|RUSTIC|Porci[oó]n\s+de\s+terreno|Solar|Finca|Predio).{10,200}(?:colinda|consta|cabida)', text_p2, re.IGNORECASE | re.DOTALL)
            
            extracto = limpiar(match_desc.group(0))[:150] + "..." if match_desc else ""
            
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
            text_p3 = pdf_pagina_a_texto(doc, 2)
            
            fecha = extraer_fecha(text_p3)
            
            # Si no encuentra fecha en página 3, intentar con página 4 (Autorización)
            if fecha == "NO ENCONTRADO" and num_paginas >= 4:
                text_p4_temp = pdf_pagina_a_texto(doc, 3)
                # Buscar fecha específica cerca de "Fecha:" en página 4
                match_fecha_p4 = re.search(r'Fecha[:\s]*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', text_p4_temp, re.IGNORECASE)
                if match_fecha_p4:
                    fecha = match_fecha_p4.group(1)
            
            datos["pagina_3_fecha"]["fecha_detectada"] = fecha
        
        # =========================================================
        # PÁGINA 4: AUTORIZACIÓN (CRÍTICO)
        # =========================================================
        if num_paginas >= 4:
            print("  Leyendo Página 4 (Autorización - CRÍTICO)...")
            text_p4 = pdf_pagina_a_texto(doc, 3)
            
            # Intentar extraer nombre de página 4
            nombre_p4 = extraer_nombre_solicitante(text_p4)
            
            # Obtener nombre maestro de página 1
            nombre_maestro = datos["pagina_1_datos"].get("nombre_solicitante", "")
            
            # Si no encuentra, es genérico, usar página 1
            if nombre_p4 in ["NO ENCONTRADO", "Estimado Cliente"] or len(nombre_p4) < 5:
                if nombre_maestro and nombre_maestro != "NO ENCONTRADO":
                    nombre_p4 = nombre_maestro
            else:
                # Corregir nombres truncados por OCR
                # Nombres comunes que podrían perder la primera letra
                correcciones_nombres = {
                    'NDRES': 'ANDRES',
                    'ARLOS': 'CARLOS', 
                    'ARIA': 'MARIA',
                    'OSE': 'JOSE',
                    'UIS': 'LUIS',
                    'AVIER': 'JAVIER',
                    'EDRO': 'PEDRO',
                    'UAN': 'JUAN',
                    'ANUEL': 'MANUEL',
                }
                
                nombre_p4_upper = nombre_p4.upper().strip()
                palabras = nombre_p4_upper.split()
                palabras_corregidas = []
                
                for palabra in palabras:
                    corregida = False
                    for truncado, completo in correcciones_nombres.items():
                        if palabra.startswith(truncado):
                            palabras_corregidas.append(completo + palabra[len(truncado):])
                            corregida = True
                            break
                    if not corregida:
                        palabras_corregidas.append(palabra)
                
                nombre_p4 = ' '.join(palabras_corregidas)
                
                # Comparar con nombre maestro y usar el más completo
                if nombre_maestro and nombre_maestro != "NO ENCONTRADO":
                    nombre_maestro_upper = nombre_maestro.upper().strip()
                    
                    # Si p4 está contenido en maestro, usar maestro
                    if nombre_p4.upper() in nombre_maestro_upper:
                        nombre_p4 = nombre_maestro
                    # Si comparten apellido, usar el más largo
                    elif nombre_p4.split()[-1] == nombre_maestro_upper.split()[-1]:
                        if len(nombre_p4.split()) < len(nombre_maestro_upper.split()):
                            nombre_p4 = nombre_maestro
            
            # Buscar número de solicitud (puede ser el número de préstamo 070XXXXXXX)
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
                "num_solicitud": num_solicitud,  # Se actualizará después si se encuentra en otras páginas
                "linea_rechazo_seguro": estado_linea,
                "estado_firma": estado_firma,
                "detalle_firma": texto_firma if texto_firma else None
            }
            # Guardar referencia para actualizar después
            num_solicitud_p4 = num_solicitud
        
        # =========================================================
        # PÁGINA 5: DIVULGACIONES / PRÉSTAMO
        # =========================================================
        if num_paginas >= 5:
            print("  Leyendo Página 5 (Préstamo)...")
            text_p5 = pdf_pagina_a_texto(doc, 4)
            
            # Usar método detallado para mejor extracción de números
            text_p5_detallado = pdf_pagina_a_texto_detallado(doc, 4)
            
            num_prestamo = extraer_numero(text_p5_detallado, ['préstamo', 'prestamo', 'Número de préstamo'])
            if num_prestamo == "NO ENCONTRADO":
                num_prestamo = extraer_numero(text_p5, ['préstamo', 'prestamo', 'Número'])
            
            nombre_maestro = datos["pagina_1_datos"].get("nombre_solicitante", "")
            nombre_en_p5 = "NO VERIFICABLE"
            
            if nombre_maestro and nombre_maestro != "NO ENCONTRADO":
                nombre_maestro_upper = nombre_maestro.upper()
                text_p5_upper = text_p5.upper()
                
                # 1. Búsqueda exacta o parcial fuerte
                if nombre_maestro_upper in text_p5_upper:
                    nombre_en_p5 = "CONFIRMADO (Exacto)"
                else:
                    # 2. Búsqueda por palabras clave (token set ratio manual)
                    partes = [p for p in nombre_maestro_upper.split() if len(p) > 2]
                    if not partes:
                        coincidencias = 0
                    else:
                        coincidencias = 0
                        for p in partes:
                            # Usar difflib para comparar palabra por palabra con el texto
                            # Esto es costoso, así que buscamos substrings aproximados
                            if p in text_p5_upper:
                                coincidencias += 1
                            else:
                                # Búsqueda difusa de la palabra en el texto (lento pero efectivo)
                                # Buscamos si hay alguna palabra en el texto que se parezca mucho a 'p'
                                palabras_texto = text_p5_upper.split()
                                mejor_match = 0
                                for pt in palabras_texto:
                                    if abs(len(pt) - len(p)) > 2: continue
                                    r = difflib.SequenceMatcher(None, p, pt).ratio()
                                    if r > 0.85:
                                        mejor_match = r
                                        break
                                if mejor_match > 0.85:
                                    coincidencias += 1
                    
                    if coincidencias >= len(partes):
                        nombre_en_p5 = "CONFIRMADO (Coincidencia completa palabras)"
                    elif coincidencias >= len(partes) * 0.7: # 70% de las palabras coinciden
                        nombre_en_p5 = "CONFIRMADO (Mayoría de palabras)"
                    elif coincidencias >= 1:
                        nombre_en_p5 = "PARCIAL (Alguna coincidencia)"
                    else:
                        # 3. Intento final: buscar similitud difusa en líneas candidatas
                        # Buscar líneas que contengan al menos una palabra del nombre
                        lineas_candidatas = []
                        for linea in text_p5_upper.split('\n'):
                            if any(p in linea for p in partes):
                                lineas_candidatas.append(linea)
                        
                        mejor_similitud_total = 0
                        for linea in lineas_candidatas:
                            sim = difflib.SequenceMatcher(None, nombre_maestro_upper, linea).ratio()
                            if sim > mejor_similitud_total:
                                mejor_similitud_total = sim
                        
                        if mejor_similitud_total > 0.6:
                             nombre_en_p5 = f"CONFIRMADO (Similitud de línea {mejor_similitud_total:.2f})"
                        else:
                            nombre_en_p5 = "NO ENCONTRADO en página"
            
            firmado, tipo_firma, texto_firma = detectar_firma_en_texto(text_p5)
            estado_firma = f"{'FIRMADO' if firmado else 'FALTA FIRMA'} ({tipo_firma})"
            if not firmado:
                datos["alertas"].append("Pág 5: Falta firma del solicitante.")
            
            datos["pagina_5_divulgacion"] = {
                "num_prestamo": num_prestamo,
                "validacion_nombre": nombre_en_p5,
                "estado_firma": estado_firma,
                "detalle_firma": texto_firma if texto_firma else None
            }
        
        # =========================================================
        # PÁGINA 6: SEGURO DE TÍTULO
        # =========================================================
        if num_paginas >= 6:
            print("  Leyendo Página 6 (Título)...")
            text_p6 = pdf_pagina_a_texto(doc, 5)
            
            # Usar método detallado para mejor extracción
            text_p6_detallado = pdf_pagina_a_texto_detallado(doc, 5)
            
            num_solicitud_p6 = extraer_numero(text_p6_detallado, ['solicitud', 'Solicitud', 'Número', 'préstamo'])
            if num_solicitud_p6 == "NO ENCONTRADO":
                num_solicitud_p6 = extraer_numero(text_p6, ['solicitud', 'Solicitud', 'Número'])
            
            # Si aún no encuentra, usar el número de préstamo de página 5 si existe
            if num_solicitud_p6 == "NO ENCONTRADO":
                num_prestamo_p5 = datos.get("pagina_5_divulgacion", {}).get("num_prestamo", "")
                if num_prestamo_p5 and num_prestamo_p5 != "NO ENCONTRADO":
                    num_solicitud_p6 = num_prestamo_p5
            
            firmado = False
            tipo_firma = "No encontrada"
            texto_firma = None
            
            match_ts = re.search(r'([A-ZÁÉÍÓÚÑ]+\s+[A-ZÁÉÍÓÚÑ]+)\s+(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?)', text_p6)
            if match_ts:
                firmado = True
                tipo_firma = "Firma Digital (Timestamp)"
                texto_firma = f"{match_ts.group(1)} - {match_ts.group(2)}"
            
            if not firmado and re.search(r'\bX+\b', text_p6):
                firmado = True
                tipo_firma = "Firma con X"
                texto_firma = "Marca X detectada"
            
            if not firmado:
                match_nombre = re.search(r'Certifico[^\n]*\n\s*([A-ZÁÉÍÓÚÑ]+\s+[A-ZÁÉÍÓÚÑ]+)', text_p6, re.IGNORECASE)
                if match_nombre:
                    firmado = True
                    tipo_firma = "Firma de Texto"
                    texto_firma = match_nombre.group(1)
            
            if not firmado:
                match_ts2 = re.search(r'(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*(?:AM|PM)?(?:\s*PDT)?)', text_p6)
                if match_ts2:
                    firmado = True
                    tipo_firma = "Firma Digital (Timestamp)"
                    texto_firma = match_ts2.group(1)
            
            estado_firma = f"{'FIRMADO' if firmado else 'FALTA FIRMA'} ({tipo_firma})"
            if not firmado:
                datos["alertas"].append("Pág 6: Falta firma del solicitante.")
            
            datos["pagina_6_titulo"] = {
                "num_solicitud": num_solicitud_p6,
                "estado_firma": estado_firma,
                "detalle_firma": texto_firma
            }
        
        doc.close()
        
        # =========================================================
        # POST-PROCESO: Actualizar campos faltantes con datos de otras páginas
        # =========================================================
        # Si num_solicitud de página 4 está vacío, usar el de página 5 o 6
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
    archivos = glob.glob("*.pdf")
    
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
            f.write("REPORTE DE VERIFICACIÓN DE COTIZACIONES\n")
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
