"""
Modelo de dominio: Palabra con coordenadas de posición.

¿Por qué existe este modelo?
Algunos bancos (BBVA, Banorte, Scotiabank) no separan claramente cargos
y abonos con texto — la única forma de distinguirlos es por su posición
horizontal (coordenada X) en la página PDF.

pdfplumber.extract_words() devuelve diccionarios con esta información.
WordInfo es nuestra versión tipada e inmutable de esos diccionarios.

No todos los parsers necesitan palabras con posición. Los que solo
necesitan texto plano usan PageText.text y ignoran PageText.words.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WordInfo:
    """Una palabra individual extraída de un PDF con sus coordenadas.

    El sistema de coordenadas de pdfplumber es:
    - Origen (0, 0) en la esquina SUPERIOR IZQUIERDA de la página.
    - X crece hacia la derecha.
    - Y (top/bottom) crece hacia abajo.
    - Unidades en puntos PDF (1 punto = 1/72 pulgada).

    Ejemplo visual de una línea de estado de cuenta BBVA:

        x0=50        x0=350       x0=420       x0=480
        |            |            |            |
        05/OCT       15,000.00    (vacío)      120,000.00
        ↑ fecha      ↑ cargo      ↑ abono      ↑ saldo
    """

    text: str
    """El texto de la palabra. Ejemplo: '15,000.00', 'PAGO', 'OCT'."""

    x0: float
    """Coordenada X del borde izquierdo de la palabra.
    Es la coordenada clave para clasificar columnas (cargo vs abono vs saldo)."""

    x1: float
    """Coordenada X del borde derecho de la palabra."""

    top: float
    """Coordenada Y del borde superior. Junto con bottom, define la línea
    vertical donde está la palabra. Palabras con top similar están en la
    misma línea visual."""

    bottom: float
    """Coordenada Y del borde inferior."""

    @property
    def center_x(self) -> float:
        """Centro horizontal de la palabra. Útil cuando las palabras varían
        ligeramente en alineación pero pertenecen a la misma columna."""
        return (self.x0 + self.x1) / 2

    @property
    def center_y(self) -> float:
        """Centro vertical de la palabra."""
        return (self.top + self.bottom) / 2
