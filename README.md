# ScriptsPITA - Pipeline de Procesamiento de Cotizaciones

Sistema automatizado para procesar paquetes de documentos de préstamos hipotecarios de Popular Mortgage. Extrae información estructurada de PDFs escaneados mediante OCR y genera reportes JSON/TXT para integración con RPA.

## 📋 Descripción

El sistema procesa documentos de cotización de pólizas de título, detectando automáticamente:
- **Cartas de Solicitud** - Datos del solicitante, hipoteca, precio de venta
- **Estudios de Título** - Número de finca, tipo de propiedad, fecha
- **Autorizaciones de Seguros** - Validación de firmas y campos requeridos
- **Divulgaciones** - Verificación de firmas electrónicas y manuscritas

## 🏗️ Estructura del Proyecto

```
ScriptsPITA/
├── pipeline.py                    # Orquestador principal del pipeline
├── script-popular-master/         # Módulos de procesamiento
│   ├── convertir_a_searchable.py  # OCR con Tesseract
│   ├── verificar_prestamos_v3.py  # Extracción y validación de datos
│   └── detector_firmas.py         # Detección de firmas
├── inicializar_estructura.py      # Crear estructura de carpetas
├── cotizaciones_temp_handler.py   # Helper para archivos temporales
│
└── BotPITA/                       # Carpetas de trabajo
    ├── Inbox/                     # PDFs de entrada (se eliminan después)
    ├── Processing_OCR/            # PDFs con OCR (temporales)
    ├── Done_JSON/                 # JSONs generados (para RPA)
    ├── Processing_TXT/            # TXTs legibles
    ├── Historial_OCR/             # PDFs archivados
    ├── Error/                     # PDFs problemáticos
    └── Logs/                      # Logs de estado
```

## 🚀 Uso Rápido

### 1. Instalar dependencias

```bash
pip install -r requirements.txt
```

### 2. Colocar PDFs en Inbox

```bash
# Copiar PDFs a procesar
copy *.pdf BotPITA\Inbox\
```

### 3. Ejecutar pipeline

```bash
python pipeline.py
```

## 📊 Flujo de Procesamiento

```
┌─────────────────────────────────────────────────────────────┐
│  1. ENTRADA                                                 │
│     BotPITA/Inbox/*.pdf                                     │
│     - Archivos individuales: documento-1-1.pdf, etc.        │
│     - Archivos sueltos: CV.PDF, DIV.PDF, ET.PDF             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  2. AGRUPACIÓN                                              │
│     - Patrón -X-Y.pdf → Grupo por nombre base              │
│     - Sin patrón → PAQUETE_YYYYMMDDHHMMSS                  │
│     - Orden: CV → ET → Page → DIV → DIV(1) → DIV(2)        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  3. MERGE + OCR                                             │
│     - Une PDFs del grupo en uno solo                        │
│     - Aplica OCR con Tesseract (español + inglés)          │
│     - Genera PDF con capa de texto seleccionable           │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  4. EXTRACCIÓN DE DATOS                                     │
│     - Detecta tipo de cada página                          │
│     - Extrae campos según configuración                    │
│     - Detecta firmas (electrónicas y manuscritas)          │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  5. VALIDACIÓN                                              │
│     - Nombre consistente entre documentos                  │
│     - Número de solicitud consistente                      │
│     - Firmas completas en documentos requeridos            │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│  6. SALIDA                                                  │
│     ✅ Done_JSON/nombre.json    → Para RPA                 │
│     ✅ Processing_TXT/nombre.txt → Legible                 │
│     ✅ Historial_OCR/nombre.pdf → Archivado                │
│     🗑️ Inbox/ → Borrados                                   │
│     🗑️ Processing_OCR/ → Borrados (temporales)             │
└─────────────────────────────────────────────────────────────┘
```

## 📄 Tipos de Documento Detectados

| Tipo | Identificadores | Campos Extraídos |
|------|-----------------|------------------|
| `CARTA_SOLICITUD` | "Solicitud de Cotización", "popularMortgage.com" | nombre, dirección, SSN, email, hipoteca, precio_venta |
| `ESTUDIO_TITULO` | "ESTUDIO", "Capital Title", "RAC TITLES" | finca, tipo_propiedad, fecha_documento |
| `AUTORIZACION_SEGUROS` | "Autorización para referir" | nombre, num_solicitud, firma |
| `DIVULGACIONES_PRODUCTOS` | "Divulgaciones relacionadas a los productos" | num_solicitud, firma |
| `DIVULGACIONES_TITULO` | "Divulgaciones Seguro de Título" | num_solicitud, firma |

## 📋 Formato JSON de Salida

```json
{
  "archivo": "COTIZACION_1911_CV_2_OCR.pdf",
  "total_paginas": 6,
  "resumen_validacion": "APROBADO",
  "documentos_detectados": {
    "CARTA_SOLICITUD": {
      "paginas": [1],
      "datos": {
        "nombre_solicitante": "LUIS JAVIER HERNANDEZ",
        "direccion_postal": "P O BOX 761 Castaner PR 00631",
        "ssn": "598-40-0570",
        "email": "luisjavier3ljhr@gmail.com",
        "cantidad_hipoteca": "$156,550.00",
        "precio_venta": "$155,000.00"
      }
    },
    "ESTUDIO_TITULO": {
      "paginas": [2],
      "datos": {
        "finca": "16,602",
        "tipo_propiedad": "CASA",
        "fecha_documento": "14 de octubre de 2025"
      }
    },
    "AUTORIZACION_SEGUROS": {
      "paginas": [4],
      "datos": {
        "nombre_solicitante": "LUIS JAVIER HERNANDEZ RAMOS",
        "num_solicitud": "0703551911",
        "firma": {
          "presente": true,
          "tipo": "Firma Manuscrita",
          "detalle": "Firma manuscrita detectada (197 trazos, 15.6% tinta)"
        }
      }
    }
  },
  "validaciones": {
    "nombre_consistente": true,
    "numero_solicitud_consistente": true,
    "firmas_completas": true
  },
  "alertas": []
}
```

## ⚙️ Configuración

### Carpetas (en `pipeline.py`)

```python
CARPETAS = {
    "entrada": "BotPITA/Inbox",           # PDFs de entrada
    "ocr": "BotPITA/Processing_OCR",      # PDFs con OCR (temporal)
    "error": "BotPITA/Error",             # PDFs problemáticos
    "resultados": "BotPITA/Done_JSON",    # JSONs generados
    "resultados_txt": "BotPITA/Processing_TXT",  # TXTs legibles
    "logs": "BotPITA/Logs",               # Logs de estado
    "historial": "BotPITA/Historial_OCR", # PDFs archivados
}
```

### Límites

```python
MAX_ERRORES = 2      # Errores antes de mover a Error/
MAX_EDAD_TMP = 3600  # Segundos para limpiar .tmp huérfanos
```

## 🔧 Dependencias

### Requeridas

```
PyMuPDF>=1.23.0      # Lectura de PDFs (fitz)
pypdfium2>=4.0.0     # Renderizado de PDFs
pytesseract>=0.3.10  # OCR
Pillow>=10.0.0       # Procesamiento de imágenes
PyPDF2>=3.0.0        # Merge de PDFs
```

### Opcionales (mejoran detección de firmas)

```
opencv-python>=4.8.0  # Detección de firmas manuscritas
numpy>=1.24.0         # Procesamiento de imágenes
```

### Tesseract OCR

Instalar Tesseract OCR:
- Windows: [UB Mannheim](https://github.com/UB-Mannheim/tesseract/wiki)
- Ruta esperada: `C:\Program Files\Tesseract-OCR\tesseract.exe`

## 📝 Log de Estado

El archivo `BotPITA/Logs/estado_procesamiento.csv` registra:

```csv
archivo;etapa;resultado;timestamp;mensaje;intento_num
COTIZACION_1911_CV_2;COMPLETO;OK;2025-12-18T14:44:30;6 PDFs procesados;1
```

## 🎯 Estados de Validación

| Estado | Descripción |
|--------|-------------|
| `APROBADO` | Todas las validaciones pasaron |
| `REVISIÓN REQUERIDA` | Hay alertas que revisar |
| `INCOMPLETO` | Faltan documentos o firmas |

## 🔍 Detección de Firmas

El sistema detecta múltiples tipos de firmas:

1. **Firma Electrónica (Timestamp)**: `NOMBRE FECHA HORA TIMEZONE`
2. **Firma Electrónica**: Nombre después de certificación
3. **Firma con Marca X**: Patrón "X" antes de línea de firma
4. **Firma Manuscrita**: Trazos detectados con OpenCV (si disponible)

## 📁 Ejemplo de Uso con Power Automate

```bash
# Procesar archivo individual
python script-popular-master/verificar_prestamos_v3.py --input archivo.pdf --output-dir salida/
```

## 🛠️ Troubleshooting

### "OCR no disponible"
```bash
pip install pypdfium2 pytesseract Pillow PyPDF2
```

### "Tesseract no encontrado"
Verificar instalación en:
- `C:\Program Files\Tesseract-OCR\tesseract.exe`
- `C:\Program Files (x86)\Tesseract-OCR\tesseract.exe`

### PDFs sin texto extraído
- Verificar que Tesseract tenga idiomas instalados (spa+eng)
- Los PDFs muy dañados o de baja calidad pueden fallar

## 📄 Licencia

Uso interno - Popular Mortgage / Popular Insurance

---

**Versión**: 3.0  
**Última actualización**: Diciembre 2025

