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
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PageText:
    """Texto extraído de una página individual de un documento."""

    page_num: int
    """Número de página (1-indexed). La primera página es 1, no 0."""

    text: str
    """Texto completo de la página. Puede contener saltos de línea."""

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
