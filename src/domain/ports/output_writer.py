"""
Puerto de salida: Escritor de resultados.

Define el contrato para escribir los resultados del parseo en
algún formato persistente (Excel, CSV, etc.).

¿Por qué es un puerto de SALIDA?
Porque el dominio (orquestador, parsers) no decide NI conoce el formato
de salida. Solo produce un ResultadoParseo y lo pasa a quien implemente
este puerto. Hoy es Excel; mañana podría ser CSV, JSON, base de datos,
o una API REST. Ningún cambio en el dominio.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from src.domain.models.resultado_parseo import ResultadoParseo


class OutputWriter(ABC):
    """Interfaz para escribir resultados de parseo."""

    @abstractmethod
    def write_single(self, resultado: ResultadoParseo, output_path: Path) -> Path:
        """Escribe el resultado de un solo estado de cuenta.

        Genera un archivo con los movimientos de un único banco/periodo.
        Corresponde al layout: Hoja 1 = Resumen, Hoja 2 = Movimientos.

        Args:
            resultado: Resultado del parseo de un estado de cuenta.
            output_path: Ruta donde crear el archivo de salida.

        Returns:
            Ruta real del archivo creado (puede diferir si se añadió extensión).

        Raises:
            OutputError: Si falla la escritura (permisos, disco lleno, etc.)
        """
        ...

    @abstractmethod
    def write_consolidated(self, resultados: list[ResultadoParseo], output_path: Path) -> Path:
        """Escribe la consolidación de múltiples estados de cuenta.

        Genera un archivo con:
        - Hoja 1: Resumen de depósitos y retiros de TODOS los archivos.
        - Hoja 2: Todos los movimientos de todos los archivos, ordenados
                   por fecha.

        Args:
            resultados: Lista de resultados de parseo.
            output_path: Ruta donde crear el archivo consolidado.

        Returns:
            Ruta real del archivo creado.

        Raises:
            OutputError: Si falla la escritura.
        """
        ...
