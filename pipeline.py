"""
Pipeline de Procesamiento de Cotizaciones
==========================================
Orquesta el flujo completo: OCR -> JSON -> Movimiento de archivos

Estructura de carpetas:
    Cotizaciones/           <- PDFs originales (se quedan aqui)
    Cotizaciones_OCR/       <- PDFs con OCR aplicado
    Cotizaciones_Error/     <- PDFs que fallaron 3+ veces
    Resultados_Pendientes/  <- JSONs para el RPA
    Resultados_TXT/         <- TXTs legibles
    logs/                   <- estado_procesamiento.csv

Uso:
    python pipeline.py
"""

import os
import re
import json
import shutil
import sys
import time
from datetime import datetime
from glob import glob

# =============================================================================
# CONFIGURAR PATH PARA IMPORTAR DESDE script-popular-master/
# =============================================================================
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_PATH = os.path.join(_SCRIPT_DIR, 'script-popular-master')
if _SCRIPTS_PATH not in sys.path:
    sys.path.insert(0, _SCRIPTS_PATH)

# Importar funciones de los scripts en script-popular-master/
from convertir_a_searchable import convertir_pdf_a_searchable
from verificar_prestamos_v3 import procesar_paquete, validar_consistencia, generar_reporte, merge_pdfs


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

# Carpetas del pipeline
CARPETAS = {
    "entrada": "BotPITA/Inbox",
    "ocr": "BotPITA/Processing_OCR",
    "error": "BotPITA/Error",
    "resultados": "BotPITA/Done_JSON",
    "resultados_txt": "BotPITA/Processing_TXT",
    "logs": "BotPITA/Logs",
    "historial": "BotPITA/Historial_OCR",
}

# Archivo de log
LOG_FILE = os.path.join(CARPETAS["logs"], "estado_procesamiento.csv")

# Límite de errores antes de mover a Cotizaciones_Error
MAX_ERRORES = 2

# Tiempo máximo para archivos .tmp huérfanos (en segundos)
MAX_EDAD_TMP = 3600  # 1 hora


# =============================================================================
# FUNCIONES DE UTILIDAD
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


def extraer_numero_pagina(ruta_pdf):
    """Extrae número de página del nombre: archivo-X-Y.pdf → X"""
    nombre = os.path.basename(ruta_pdf)
    match = re.search(r'-(\d+)-\d+\.pdf$', nombre, re.IGNORECASE)
    return int(match.group(1)) if match else 0


def extraer_orden_documento(ruta_pdf):
    """
    Asigna un orden basado en el tipo de documento detectado por nombre.
    Orden estándar: CV/Carta → ET/Estudio → Page/Continuación → DIV/Divulgaciones
    """
    nombre = os.path.basename(ruta_pdf).upper()
    
    # Orden por tipo de documento
    if 'CV' in nombre or 'CARTA' in nombre or 'COTIZACION' in nombre:
        return (1, nombre)  # Carta de Solicitud primero
    elif 'ET' in nombre or 'ESTUDIO' in nombre:
        return (2, nombre)  # Estudio de Título
    elif 'PAGE' in nombre or 'PAG' in nombre or 'CONTINUACION' in nombre:
        return (3, nombre)  # Continuaciones
    elif 'DIV' in nombre:
        # Ordenar DIV, DIV(1), DIV(2) correctamente
        match = re.search(r'DIV\s*\((\d+)\)', nombre)
        if match:
            return (4 + int(match.group(1)), nombre)  # DIV(1)=5, DIV(2)=6
        return (4, nombre)  # DIV sin número = 4
    else:
        return (10, nombre)  # Otros al final


def agrupar_pdfs_por_base(lista_pdfs):
    """
    Agrupa PDFs por nombre base (sin número de página).
    'COTIZACION 1911 CV (2)-1-1.pdf' → grupo 'COTIZACION_1911_CV_2'
    'COTIZACION 1911 CV (2)-2-2.pdf' → mismo grupo
    
    Para documentos sin patrón -X-Y.pdf (como CV.PDF, DIV.PDF, etc.),
    los agrupa todos juntos como grupo 'PAQUETE_SIN_NOMBRE'.
    """
    grupos = {}
    sin_patron = []
    
    for pdf in lista_pdfs:
        nombre = os.path.basename(pdf)
        # Verificar si tiene patrón -X-Y.pdf
        if re.search(r'-\d+-\d+\.pdf$', nombre, re.IGNORECASE):
            # Quitar sufijo -X-Y.pdf
            base = re.sub(r'-\d+-\d+\.pdf$', '', nombre, flags=re.IGNORECASE)
            clave = sanitizar_nombre(base)
            grupos.setdefault(clave, []).append(pdf)
        else:
            # No tiene patrón estándar, agregar a lista de sin patrón
            sin_patron.append(pdf)
    
    # Si hay documentos sin patrón, agruparlos juntos
    if sin_patron:
        # Intentar extraer un identificador común (número de caso, etc.)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        clave = f"PAQUETE_{timestamp}"
        grupos[clave] = sin_patron
    
    # Ordenar archivos dentro de cada grupo
    for clave in grupos:
        if clave.startswith("PAQUETE_"):
            # Ordenar por tipo de documento (CV primero, luego ET, luego DIV)
            grupos[clave].sort(key=lambda x: extraer_orden_documento(x))
        else:
            # Ordenar por número de página
            grupos[clave].sort(key=lambda x: extraer_numero_pagina(x))
    
    return grupos


def crear_carpetas():
    """Crea todas las carpetas necesarias si no existen."""
    for nombre, carpeta in CARPETAS.items():
        if not os.path.exists(carpeta):
            os.makedirs(carpeta)
            print(f"  Carpeta creada: {carpeta}/")


def inicializar_log():
    """Crea el archivo de log CSV si no existe."""
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("archivo;etapa;resultado;timestamp;mensaje;intento_num\n")


# =============================================================================
# FUNCIONES DE LOG
# =============================================================================

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


# =============================================================================
# FUNCIONES DE LIMPIEZA
# =============================================================================

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


# =============================================================================
# FUNCIONES DE PROCESAMIENTO
# =============================================================================

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


def generar_json(nombre_pdf, ruta_pdf_ocr, ruta_json_final, ruta_txt_final):
    """
    Genera el JSON y TXT a partir del PDF con OCR.
    Usa escritura atomica (.tmp -> .json/.txt).
    
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


def mover_archivo(origen, destino):
    """Mueve un archivo de una carpeta a otra."""
    if os.path.exists(origen):
        # Si ya existe en destino, eliminarlo primero
        if os.path.exists(destino):
            os.remove(destino)
        shutil.move(origen, destino)
        return True
    return False


# =============================================================================
# FUNCIÓN PRINCIPAL: PROCESAR GRUPO DE PDFs
# =============================================================================

def procesar_grupo(nombre_grupo, lista_pdfs):
    """
    Procesa un grupo de PDFs como UNA sola unidad.
    
    Flujo:
        1. Merge → un solo PDF
        2. OCR al merged
        3. JSON + TXT únicos
        4. Mover PDF final a Historial
        5. Limpiar: borrar originales de Inbox y temporales de Processing_OCR
    
    Returns:
        str: "OK", "ERROR", "IGNORADO"
    """
    print(f"\n{'='*60}")
    print(f"GRUPO: {nombre_grupo} ({len(lista_pdfs)} archivos)")
    for pdf in lista_pdfs:
        print(f"  - {os.path.basename(pdf)}")
    
    # Rutas
    ruta_merged = os.path.join(CARPETAS["ocr"], f"{nombre_grupo}_merged.pdf")
    ruta_ocr = os.path.join(CARPETAS["ocr"], f"{nombre_grupo}_OCR.pdf")
    ruta_json = os.path.join(CARPETAS["resultados"], f"{nombre_grupo}.json")
    ruta_txt = os.path.join(CARPETAS["resultados_txt"], f"{nombre_grupo}.txt")
    ruta_historial = os.path.join(CARPETAS["historial"], f"{nombre_grupo}.pdf")
    
    # --- Si JSON ya existe, ignorar ---
    if os.path.exists(ruta_json):
        print(f"  [--] JSON ya existe, ignorando grupo")
        return "IGNORADO"
    
    # --- Verificar límite de errores ---
    errores = contar_errores(nombre_grupo)
    if errores >= MAX_ERRORES:
        print(f"  [!!] Limite de errores alcanzado ({errores}), moviendo a Error/")
        for pdf in lista_pdfs:
            ruta_error = os.path.join(CARPETAS["error"], os.path.basename(pdf))
            mover_archivo(pdf, ruta_error)
        escribir_log(nombre_grupo, "MOVIDO_ERROR", "LIMITE", f"{errores} errores", "-")
        return "LIMITE_ERRORES"
    
    try:
        # --- Paso 1: Merge ---
        print(f"  [>>] Paso 1: Uniendo {len(lista_pdfs)} PDFs...")
        if len(lista_pdfs) == 1:
            shutil.copy2(lista_pdfs[0], ruta_merged)
        else:
            merge_pdfs(lista_pdfs, ruta_merged)
        print(f"  [OK] Merged: {nombre_grupo}_merged.pdf")
        
        # --- Paso 2: OCR ---
        print(f"  [>>] Paso 2: Aplicando OCR...")
        exito = hacer_ocr(nombre_grupo, ruta_merged, ruta_ocr)
        if not exito:
            raise Exception("OCR fallo")
        print(f"  [OK] OCR completado: {nombre_grupo}_OCR.pdf")
        
        # --- Paso 3: JSON + TXT ---
        print(f"  [>>] Paso 3: Generando JSON y TXT...")
        generar_json(nombre_grupo, ruta_ocr, ruta_json, ruta_txt)
        print(f"  [OK] JSON: {nombre_grupo}.json")
        print(f"  [OK] TXT: {nombre_grupo}.txt")
        
        # --- Paso 4: Mover a Historial ---
        print(f"  [>>] Paso 4: Archivando en Historial...")
        shutil.move(ruta_ocr, ruta_historial)
        print(f"  [OK] Archivado: Historial_OCR/{nombre_grupo}.pdf")
        
        # --- Paso 5: Limpieza ---
        print(f"  [>>] Paso 5: Limpiando archivos procesados...")
        
        # Borrar PDFs originales de Inbox
        for pdf in lista_pdfs:
            try:
                os.remove(pdf)
                print(f"      [DEL] Inbox: {os.path.basename(pdf)}")
            except Exception as e:
                print(f"      [ERR] No se pudo borrar {os.path.basename(pdf)}: {e}")
        
        # Borrar merged temporal de Processing_OCR
        if os.path.exists(ruta_merged):
            os.remove(ruta_merged)
            print(f"      [DEL] Processing_OCR: {nombre_grupo}_merged.pdf")
        
        escribir_log(nombre_grupo, "COMPLETO", "OK", f"{len(lista_pdfs)} PDFs procesados", 1)
        print(f"  [OK] Grupo {nombre_grupo} completado exitosamente")
        return "OK"
        
    except Exception as e:
        print(f"  [ERROR] {e}")
        escribir_log(nombre_grupo, "ERROR", "ERROR", str(e)[:100], 1)
        # Limpiar temporales en caso de error
        for tmp in [ruta_merged]:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except:
                    pass
        return "ERROR"


# =============================================================================
# FUNCIÓN LEGACY: PROCESAR PDF INDIVIDUAL (mantenida por compatibilidad)
# =============================================================================

def procesar_pdf(nombre_pdf):
    """
    Procesa un PDF individual a través del pipeline completo.
    
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
        print(f"  [!!] Limite de errores alcanzado ({errores}), moviendo a Error/")
        mover_archivo(ruta_entrada, ruta_error)
        escribir_log(nombre_pdf, "MOVIDO_ERROR", "LIMITE", f"{errores} errores acumulados", "-")
        return "LIMITE_ERRORES"
    
    # --- Paso 1: OCR ---
    if not os.path.exists(ruta_ocr):
        print(f"  [>>] Paso 1: Aplicando OCR...")
        intento = obtener_ultimo_intento(nombre_pdf, "OCR") + 1
        
        try:
            exito = hacer_ocr(nombre_pdf, ruta_entrada, ruta_ocr)
            if exito:
                print(f"  [OK] OCR completado")
                escribir_log(nombre_pdf, "OCR", "OK", "-", intento)
                # Mover PDF original a Cotizaciones_OCR/ (ya está ahí el OCR, mover el original)
                # En realidad el OCR se guarda en ruta_ocr, el original se queda hasta el final
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
        exito = generar_json(nombre_pdf, ruta_ocr, ruta_json, ruta_txt)
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


def ejecutar_pipeline():
    """
    Ejecuta el pipeline completo:
    1. Agrupa PDFs por nombre base
    2. Une cada grupo en un solo PDF
    3. Aplica OCR
    4. Genera JSON + TXT únicos por grupo
    5. Archiva en Historial y limpia Inbox/Processing_OCR
    """
    print("="*60)
    print("PIPELINE DE PROCESAMIENTO DE COTIZACIONES")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)
    
    # --- Inicialización ---
    print("\n[1/4] Inicializando carpetas...")
    crear_carpetas()
    inicializar_log()
    
    # --- Limpieza ---
    print("\n[2/4] Limpiando archivos temporales...")
    limpiar_tmp_huerfanos()
    
    # --- Listar y Agrupar PDFs ---
    print("\n[3/4] Agrupando PDFs por nombre base...")
    
    patron = os.path.join(CARPETAS["entrada"], "*.pdf")
    pdfs = sorted(glob(patron))
    
    if not pdfs:
        print(f"\n  No hay PDFs en {CARPETAS['entrada']}/")
        print("  Coloca los PDFs a procesar en esa carpeta y ejecuta de nuevo.")
        return
    
    grupos = agrupar_pdfs_por_base(pdfs)
    print(f"  Encontrados {len(pdfs)} PDFs en {len(grupos)} grupo(s):")
    for nombre, archivos in grupos.items():
        print(f"    - {nombre}: {len(archivos)} archivo(s)")
    
    # --- Procesar Grupos ---
    print("\n[4/4] Procesando grupos...")
    
    resultados = {
        "OK": 0,
        "ERROR": 0,
        "IGNORADO": 0,
        "LIMITE_ERRORES": 0,
    }
    
    for nombre_grupo, lista_pdfs in grupos.items():
        resultado = procesar_grupo(nombre_grupo, lista_pdfs)
        resultados[resultado] = resultados.get(resultado, 0) + 1
    
    # --- Resumen ---
    print("\n" + "="*60)
    print("RESUMEN DEL PIPELINE")
    print("="*60)
    print(f"  [OK] Grupos procesados:  {resultados['OK']}")
    print(f"  [--] Ignorados:          {resultados['IGNORADO']}")
    print(f"  [XX] Errores:            {resultados['ERROR']}")
    print(f"  [!!] Limite errores:     {resultados.get('LIMITE_ERRORES', 0)}")
    print("="*60)
    print(f"\nResultados:")
    print(f"  JSONs en:      {CARPETAS['resultados']}/")
    print(f"  TXTs en:       {CARPETAS['resultados_txt']}/")
    print(f"  PDFs en:       {CARPETAS['historial']}/")
    print(f"  Log en:        {LOG_FILE}")


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    ejecutar_pipeline()
