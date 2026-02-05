"""
Utilidades de limpieza de texto.

Funciones reutilizables para normalizar y limpiar texto extraído de PDFs
antes de que los bank parsers lo procesen.

Estas funciones NO tienen lógica de negocio (no saben de bancos ni montos).
Solo operan sobre strings puros.
"""

import re


def clean_whitespace(text: str) -> str:
    """Reemplaza múltiples espacios/tabs por un solo espacio y hace strip.

    Es la limpieza más básica y se usa en prácticamente todos los parsers.
    pdfplumber a veces extrae texto con espacios duplicados o tabs.

    Ejemplos:
        >>> clean_whitespace("  PAGO   NOMINA   ")
        'PAGO NOMINA'
        >>> clean_whitespace("\\tREFERENCIA\\t123")
        'REFERENCIA 123'
    """
    return re.sub(r"\s+", " ", text).strip()


def remove_non_printable(text: str) -> str:
    """Elimina caracteres no imprimibles (control chars) excepto \\n, \\r, \\t.

    ¿Cuándo se necesita? Cuando se lee texto de PDFs escaneados con OCR,
    que a veces incluyen caracteres de control invisibles que rompen los
    regex de los parsers.

    Ejemplos:
        >>> remove_non_printable("PAGO\\x00NOMINA")
        'PAGO NOMINA'
    """
    # Mantiene printables, newline, return, tab. Reemplaza el resto por espacio.
    cleaned = "".join(char if (char.isprintable() or char in "\n\r\t") else " " for char in text)
    return cleaned


def normalize_line_endings(text: str) -> str:
    """Normaliza todos los saltos de línea a \\n.

    Los PDFs pueden usar \\r\\n (Windows), \\r (Mac antiguo), o \\n (Unix).
    Normalizar asegura que split('\\n') funcione consistentemente.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def clean_pdf_text(text: str) -> str:
    """Aplica todas las limpiezas comunes en secuencia.

    Es la función de "conveniencia" que los text extractors deberían llamar
    después de extraer el texto crudo del PDF, ANTES de pasarlo al parser.

    Secuencia:
    1. Eliminar caracteres no imprimibles
    2. Normalizar saltos de línea
    (NO aplica clean_whitespace porque eso eliminaría los \\n que los
    parsers necesitan para procesar línea por línea)
    """
    text = remove_non_printable(text)
    text = normalize_line_endings(text)
    return text


def replace_special_chars(text: str) -> str:
    """Reemplaza caracteres especiales de PDFs cifrados (caso JP Morgan/HSBC).

    Algunos bancos generan PDFs donde ciertos caracteres se sustituyen por
    otros. Esto se descubrió empíricamente en el extractor de JP Morgan:
        Û → /
        Þ → ,
        Ï → ;
        Ð → :

    ¿Por qué pasa esto? Porque el PDF usa una codificación propietaria
    o un font mapping personalizado que pdfplumber no resuelve correctamente.
    """
    replacements: dict[str, str] = {
        "Û": "/",
        "Þ": ",",
        "Ï": ";",
        "Ð": ":",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def extract_between_markers(
    text: str,
    start_marker: str,
    end_marker: str | None = None,
) -> str:
    """Extrae el texto entre dos marcadores.

    Útil para extraer secciones específicas de un estado de cuenta.
    Por ejemplo, extraer solo la sección "DETALLE DE MOVIMIENTOS"
    ignorando el encabezado y pie de página.

    Args:
        text: Texto completo.
        start_marker: Texto que marca el inicio de la sección.
        end_marker: Texto que marca el fin. Si es None, toma hasta el final.

    Returns:
        Texto entre los marcadores (sin incluir los marcadores).
        Cadena vacía si no se encuentra el start_marker.
    """
    start_idx = text.find(start_marker)
    if start_idx == -1:
        return ""

    start_idx += len(start_marker)

    if end_marker is None:
        return text[start_idx:]

    end_idx = text.find(end_marker, start_idx)
    if end_idx == -1:
        return text[start_idx:]

    return text[start_idx:end_idx]
