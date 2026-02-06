"""
Modelo de dominio: Texto extraído de una página.

Este modelo actúa como el "puente" entre los adaptadores de extracción
de texto (pdfplumber, OCR, ZIP/txt) y los parsers bancarios.

¿Por qué no pasar un string crudo? Porque:
1. El número de página es necesario para algunos parsers que procesan
   la primera página diferente (extraen info de cuenta) y las demás
   (extraen movimientos).
2. Permite rastrear en qué página se encontró cada movimiento,
   útil para debugging cuando un parser falla.
3. Algunos parsers (BBVA, Banorte) necesitan las coordenadas X/Y de cada
   palabra para clasificar cargos vs abonos por posición en la página.
   El campo `words` opcional transporta esta información.
"""

from dataclasses import dataclass, field

from src.domain.models.word_info import WordInfo


@dataclass(frozen=True)
class PageText:
    """Texto extraído de una página individual de un documento.

    Dos modos de uso:
    - Solo texto: parsers que usan regex sobre el texto plano (la mayoría).
    - Texto + words: parsers que necesitan posiciones X/Y (BBVA, Banorte).

    El campo `words` es opcional. Si el TextExtractor no lo llena
    (por ejemplo, OcrExtractor), queda como lista vacía y los parsers
    que lo necesitan pueden lanzar un error descriptivo.
    """

    page_num: int
    """Número de página (1-indexed). La primera página es 1, no 0."""

    text: str
    """Texto completo de la página. Puede contener saltos de línea."""

    words: list[WordInfo] = field(default_factory=list)
    """Lista de palabras con sus coordenadas de posición en la página.
    Vacía si el extractor no soporta extracción de palabras (OCR, ZIP/txt).
    Llena cuando se usa PdfplumberExtractor con include_words=True."""

    @property
    def has_words(self) -> bool:
        """Indica si esta página tiene datos de palabras con posición.
        Los parsers que requieren posiciones deben verificar esto."""
        return len(self.words) > 0

    @property
    def is_empty(self) -> bool:
        """Indica si la página no tiene texto útil."""
        return not self.text.strip()

    @property
    def lines(self) -> list[str]:
        """Devuelve el texto dividido en líneas.

        Conveniencia para los parsers que procesan línea por línea.
        Se llama como propiedad (page.lines) en vez de método (page.lines())
        porque no recibe parámetros y siempre devuelve lo mismo.
        """
        return self.text.split("\n")
