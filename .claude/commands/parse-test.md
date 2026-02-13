# Skill: Probar parser con PDF real

Prueba el parser con un archivo PDF o directorio: **$ARGUMENTS**

## Pasos

### 1. Validar entrada
- Verifica que la ruta `$ARGUMENTS` existe.
- Si es un archivo, verifica que sea un PDF.
- Si es un directorio, verifica que contenga PDFs.

### 2. Ejecutar el parser
- Ejecuta: `python -m src.cli.main "$ARGUMENTS"`
- Captura tanto stdout como stderr.

### 3. Analizar resultado
- Si fue exitoso:
  - Muestra el banco detectado
  - Muestra el numero de movimientos extraidos
  - Muestra el resumen (total retiros, total depositos)
  - Muestra la ruta del Excel generado

- Si fallo:
  - Identifica el tipo de error (banco no identificado, error de parseo, error de extraccion)
  - Sugiere posibles causas y soluciones
  - Si el banco no fue identificado, sugiere ejecutar `/add-bank {banco}`

### 4. Verificacion cruzada (opcional)
Si el usuario lo pide, abre el Excel generado y verifica:
- Que las columnas tienen datos
- Que los montos son razonables (no hay valores extremos obvios)
- Que las fechas estan en rango valido
