SET CarpetaBase TO $'''C:\\Users\\PR65368\\Downloads\\script-popular-master\\script-popular-master'''
SET CarpetaCotizaciones TO $'''%CarpetaBase%\\Cotizaciones'''
SET CarpetaOCR TO $'''%CarpetaBase%\\CotizacionesOCR'''
SET CarpetaResultados TO $'''%CarpetaBase%\\resultados'''
SET ScriptOCR TO $'''%CarpetaBase%\\convertir_a_searchable.py'''
SET ScriptVerificar TO $'''%CarpetaBase%\\verificar_prestamos_v3.py'''
SET ContadorExitosos TO 0
SET ContadorFallidos TO 0
Variables.CreateNewList List=> ListaArchivosNuevos

# Obtener todos los PDFs de Cotizaciones

Folder.GetFiles Folder: CarpetaCotizaciones FileFilter: $'''*.pdf''' IncludeSubfolders: False Files=> ArchivosPDF

# Filtrar solo archivos nuevos (que no tengan _OCR.pdf en CarpetaOCR)

LOOP FOREACH CurrentFile IN ArchivosPDF
    File.GetPathPart File: CurrentFile RootPath=> RootPath Directory=> Directory FileName=> FileName FileNameWithoutExtension=> NombreBase Extension=> Extension
    SET RutaOCREsperada TO $'''%CarpetaOCR%\\%NombreBase%_OCR.pdf'''
    IF (File.Exists File: RutaOCREsperada) = False THEN
        Variables.AddItemToList Item: CurrentFile List: ListaArchivosNuevos NewList=> ListaArchivosNuevos
    END
END

# Verificar si hay archivos para procesar

Variables.GetListLength List: ListaArchivosNuevos Length=> CantidadNuevos

IF CantidadNuevos = 0 THEN
    Display.ShowMessageDialog Title: $'''Sin archivos nuevos''' Message: $'''No se encontraron cotizaciones nuevas para procesar.''' Icon: Display.Icon.Information Buttons: Display.Buttons.OK DefaultButton: Display.DefaultButton.Button1 IsTopMost: False ButtonPressed=> ButtonPressed
    EXIT Code: 0
END

Display.ShowMessageDialog Title: $'''Procesamiento iniciado''' Message: $'''Se encontraron %CantidadNuevos% archivos nuevos.

¿Desea continuar con el procesamiento?''' Icon: Display.Icon.Question Buttons: Display.Buttons.YesNo DefaultButton: Display.DefaultButton.Button1 IsTopMost: False ButtonPressed=> RespuestaUsuario

IF RespuestaUsuario = $'''No''' THEN
    EXIT Code: 0
END

# Procesar cada archivo nuevo

LOOP FOREACH ArchivoActual IN ListaArchivosNuevos
    File.GetPathPart File: ArchivoActual RootPath=> RootPath2 Directory=> Directory2 FileName=> FileName2 FileNameWithoutExtension=> NombreArchivo Extension=> Extension2

    # Paso 1: Ejecutar OCR
    SET ComandoOCR TO $'''python "%ScriptOCR%" --input "%ArchivoActual%" --output-dir "%CarpetaOCR%"'''
    System.RunDOSCommand DOSCommandOrApplication: ComandoOCR WorkingDirectory: CarpetaBase StandardOutput=> SalidaOCR StandardError=> ErrorOCR ExitCode=> CodigoOCR

    IF CodigoOCR <> 0 THEN
        SET ContadorFallidos TO ContadorFallidos + 1
        NEXT LOOP
    END

    # Paso 2: Ejecutar Verificación
    SET ArchivoOCR TO $'''%CarpetaOCR%\\%NombreArchivo%_OCR.pdf'''
    SET ComandoVerificar TO $'''python "%ScriptVerificar%" --input "%ArchivoOCR%" --output-dir "%CarpetaResultados%"'''
    System.RunDOSCommand DOSCommandOrApplication: ComandoVerificar WorkingDirectory: CarpetaBase StandardOutput=> SalidaVerificar StandardError=> ErrorVerificar ExitCode=> CodigoVerificar

    IF CodigoVerificar <> 0 THEN
        SET ContadorFallidos TO ContadorFallidos + 1
    ELSE
        SET ContadorExitosos TO ContadorExitosos + 1
    END
END

# Mostrar resumen final

Display.ShowMessageDialog Title: $'''Proceso completado''' Message: $'''Resumen del procesamiento:

• Archivos procesados exitosamente: %ContadorExitosos%
• Archivos con error: %ContadorFallidos%

Los resultados están en:
%CarpetaResultados%''' Icon: Display.Icon.Information Buttons: Display.Buttons.OK DefaultButton: Display.DefaultButton.Button1 IsTopMost: False ButtonPressed=> ButtonPressed2
