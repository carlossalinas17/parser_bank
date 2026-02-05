"""
Excepciones de dominio del proyecto bank-statement-parser.

¿Por qué excepciones propias en lugar de usar ValueError/RuntimeError?
Porque permiten que el código de orquestación (Orchestrator) pueda distinguir
entre "no encontré el banco" y "el PDF está corrupto" y tomar acciones
diferentes para cada caso (por ejemplo, registrar en bitácora vs reintentar
con OCR).

Jerarquía:
    ParserBaseError
    ├── BancoNoIdentificadoError    → No se pudo determinar qué banco es
    ├── FormatoInvalidoError        → El archivo no tiene el formato esperado
    ├── ExtractionError             → Error al extraer texto del archivo
    ├── ParseError                  → Error al parsear los movimientos
    └── OutputError                 → Error al generar el archivo de salida
"""


class ParserBaseError(Exception):
    """Excepción base del proyecto. Todas las demás heredan de esta.

    ¿Por qué una base común? Para poder capturar CUALQUIER error del proyecto
    con un solo `except ParserBaseError` en el orquestador, mientras que los
    handlers específicos pueden capturar subclases individuales.
    """


class BancoNoIdentificadoError(ParserBaseError):
    """Se lanza cuando el BankIdentifier no puede determinar a qué banco
    corresponde un estado de cuenta.

    Esto puede pasar porque:
    - El PDF no contiene keywords reconocibles de ningún banco registrado.
    - El texto extraído está vacío o corrupto.
    - Es un banco nuevo que aún no tiene parser implementado.
    """

    def __init__(self, archivo: str, detalle: str = ""):
        self.archivo = archivo
        self.detalle = detalle
        mensaje = f"No se pudo identificar el banco del archivo: {archivo}"
        if detalle:
            mensaje += f" — {detalle}"
        super().__init__(mensaje)


class FormatoInvalidoError(ParserBaseError):
    """Se lanza cuando un archivo no tiene el formato esperado.

    Ejemplos:
    - Se esperaba un PDF pero el archivo es un .docx.
    - El PDF no tiene páginas.
    - Un ZIP no contiene archivos .txt ni .pdf dentro.
    """

    def __init__(self, archivo: str, formato_esperado: str, detalle: str = ""):
        self.archivo = archivo
        self.formato_esperado = formato_esperado
        mensaje = f"Formato inválido en '{archivo}'. Se esperaba: {formato_esperado}"
        if detalle:
            mensaje += f" — {detalle}"
        super().__init__(mensaje)


class ExtractionError(ParserBaseError):
    """Se lanza cuando falla la extracción de texto de un archivo.

    Esto puede pasar porque:
    - El PDF está protegido con contraseña y no se proporcionó.
    - pdfplumber no puede leer el archivo.
    - Tesseract no está instalado pero se intentó OCR.
    - El archivo está corrupto.
    """

    def __init__(self, archivo: str, causa: str):
        self.archivo = archivo
        self.causa = causa
        super().__init__(f"Error extrayendo texto de '{archivo}': {causa}")


class ParseError(ParserBaseError):
    """Se lanza cuando el BankParser no puede parsear los movimientos.

    Esto puede pasar porque:
    - El formato del estado de cuenta del banco cambió.
    - El texto extraído está incompleto (OCR parcial).
    - Un regex no matchea el patrón esperado.
    """

    def __init__(self, banco: str, archivo: str, causa: str):
        self.banco = banco
        self.archivo = archivo
        self.causa = causa
        super().__init__(f"Error parseando {banco} en '{archivo}': {causa}")


class OutputError(ParserBaseError):
    """Se lanza cuando falla la generación del archivo de salida.

    Esto puede pasar porque:
    - No hay permisos de escritura en el directorio de salida.
    - El disco está lleno.
    - Hay un error en el formato del Excel.
    """

    def __init__(self, ruta_salida: str, causa: str):
        self.ruta_salida = ruta_salida
        self.causa = causa
        super().__init__(f"Error generando salida en '{ruta_salida}': {causa}")
