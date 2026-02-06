"""
Modelos de dominio del proyecto bank-statement-parser.

Todos los modelos son dataclasses inmutables (frozen=True) que representan
los datos del negocio sin dependencias externas.

Uso:
    from src.domain.models import Movimiento, InfoCuenta, ResultadoParseo
"""

from src.domain.models.info_cuenta import InfoCuenta
from src.domain.models.movimiento import Movimiento
from src.domain.models.page_text import PageText
from src.domain.models.resultado_parseo import ResultadoParseo
from src.domain.models.resumen import Resumen
from src.domain.models.word_info import WordInfo

__all__ = [
    "InfoCuenta",
    "Movimiento",
    "PageText",
    "Resumen",
    "ResultadoParseo",
    "WordInfo",
]
