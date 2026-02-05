"""
Puerto de entrada: Identificador de banco.

Define el contrato para determinar a qué banco corresponde un
estado de cuenta, basándose en el texto de las primeras páginas.

La implementación más simple es por keywords: buscar "BBVA" o
"BANCOMER" en el texto → es BBVA. Pero la interfaz permite
implementaciones más sofisticadas en el futuro (ML, pattern matching, etc.).
"""

from abc import ABC, abstractmethod


class BankIdentifier(ABC):
    """Interfaz para identificar el banco de un estado de cuenta."""

    @abstractmethod
    def identify(self, text: str) -> str | None:
        """Identifica el banco basándose en el texto del estado de cuenta.

        Típicamente se le pasa el texto de las primeras 1-2 páginas,
        que es donde aparece la información del banco.

        Args:
            text: Texto extraído de las primeras páginas del documento.

        Returns:
            Nombre del banco normalizado a mayúsculas ('BBVA', 'BANORTE', etc.)
            si se identifica exitosamente.
            None si no se puede determinar el banco.
        """
        ...
