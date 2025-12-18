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
import time
from datetime import datetime
from glob import glob

# Importar funciones de los scripts existentes
from convertir_a_searchable import convertir_pdf_a_searchable
from verificar_prestamos_v3 import procesar_paquete, validar_consistencia, generar_reporte, merge_pdfs


# =============================================================================
# CONFIGURACIÓN
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
# FUNCIÓN PRINCIPAL DEL PIPELINE
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
    """Ejecuta el pipeline completo para todos los PDFs pendientes."""
    print("="*60)
    print("PIPELINE DE PROCESAMIENTO DE COTIZACIONES")
    print(f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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


    def find_group_key(filename):
        """Key básica para agrupar archivos en `Cotizaciones_temp`.
        Busca 6-12 dígitos en el nombre; si no, usa el prefijo antes de - _ o espacio.
        """
        base = os.path.basename(filename)
        m = re.search(r'(\d{6,12})', base)
        if m:
            return m.group(1)
        prefix = re.split(r'[-_\s]', os.path.splitext(base)[0])[0]
        return prefix.lower() if prefix else base


    def process_cotizaciones_temp():
        """Si hay PDFs en `Cotizaciones_temp`, agrupa y une en `Cotizaciones/`.
        Esto permite que `python pipeline.py` también procese archivos descargados
        temporalmente sin ejecutar el helper por separado.
        """
        temp_dir = "Cotizaciones_temp"
        if not os.path.exists(temp_dir):
            return

        files = sorted(glob(os.path.join(temp_dir, "*.pdf")))
        if not files:
            return

        groups = {}
        for f in files:
            key = find_group_key(f)
            groups.setdefault(key, []).append(f)

        for key, flist in groups.items():
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            combined_name = f"{key}_{timestamp}.pdf"
            combined_path = os.path.join(CARPETAS["entrada"], combined_name)

            try:
                if len(flist) == 1:
                    shutil.copy2(flist[0], combined_path)
                else:
                    # merge_pdfs viene de verificar_prestamos_v3
                    if merge_pdfs is None:
                        print("Aviso: merge_pdfs no disponible; no se pueden unir PDFs de Cotizaciones_temp.")
                        continue
                    merge_pdfs(flist, combined_path)
                # borrar archivos temporales origen
                for src in flist:
                    try:
                        os.remove(src)
                    except:
                        pass
                print(f"  [TEMP] Generado combinado: {combined_name}")
            except Exception as e:
                print(f"  [TEMP][ERROR] al procesar grupo {key}: {e}")
    
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
        resultado = procesar_pdf(nombre_pdf)
        resultados[resultado] = resultados.get(resultado, 0) + 1
    
    # --- Resumen ---
    print("\n" + "="*60)
    print("RESUMEN DEL PIPELINE")
    print("="*60)
    print(f"  [OK] Procesados OK:     {resultados['OK']}")
    print(f"  [--] Ignorados:         {resultados['IGNORADO']}")
    print(f"  [XX] Errores:           {resultados['ERROR']}")
    print(f"  [!!] Limite errores:   {resultados['LIMITE_ERRORES']}")
    print("="*60)
    print(f"\nJSONs listos en: {CARPETAS['resultados']}/")
    print(f"Log de estado en: {LOG_FILE}")


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    ejecutar_pipeline()
