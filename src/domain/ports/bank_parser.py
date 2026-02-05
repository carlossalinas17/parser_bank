"""
Puerto de entrada: Parser de estados de cuenta bancarios.

Define el contrato que cada parser de banco debe cumplir.
Hay exactamente un BankParser por cada banco soportado:

    BankParser (interfaz)
    ├── BBVAParser
    ├── BanorteParser
    ├── CitibanamexParser
    ├── SantanderParser
    ├── ...etc (uno por banco)

¿Por qué recibe List[PageText] y no un string?
Porque muchos parsers procesan la primera página de forma diferente
(extraen info de cuenta) y las siguientes (extraen movimientos).
Tener las páginas separadas permite esta lógica sin que el parser
tenga que re-dividir el texto por páginas.

¿Por qué devuelve ResultadoParseo completo?
Porque cada parser es responsable de:
1. Extraer info de cuenta (banco, cuenta, moneda)
2. Extraer movimientos (fecha, concepto, retiro/depósito)
3. Calcular el resumen (totales)
Todo esto va junto en ResultadoParseo.
"""

from abc import ABC, abstractmethod

from src.domain.models.page_text import PageText
from src.domain.models.resultado_parseo import ResultadoParseo


class BankParser(ABC):
    """Interfaz para parsear un estado de cuenta de un banco específico."""

    @property
    @abstractmethod
    def bank_name(self) -> str:
        """Nombre del banco que este parser maneja.

        Se usa como clave en el registro de parsers (Registry).
        Debe coincidir con lo que devuelve BankIdentifier.identify().

        Debe estar normalizado a mayúsculas: 'BBVA', 'BANORTE', etc.
        """
        ...

    @abstractmethod
    def parse(self, pages: list[PageText], file_name: str = "") -> ResultadoParseo:
        """Parsea las páginas de texto y devuelve el resultado completo.

        Args:
            pages: Lista de PageText obtenidas de un TextExtractor.
                   Están en orden de página (1, 2, 3...).
            file_name: Nombre del archivo original. Para trazabilidad.

        Returns:
            ResultadoParseo con info_cuenta, movimientos y resumen.

        Raises:
            ParseError: Si no se pueden extraer los movimientos.
                        El error debe incluir contexto suficiente para
                        debuggear (banco, archivo, línea problemática).
        """
        ...
