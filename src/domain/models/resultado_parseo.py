"""
Modelo de dominio: Resultado completo del parseo de un estado de cuenta.

Este es el objeto central que fluye por toda la arquitectura:
- Lo PRODUCE cada BankParser (adaptador de entrada).
- Lo CONSUME el OutputWriter (adaptador de salida).
- Lo ACUMULA el Consolidator (servicio de dominio).
- Lo REGISTRA el ProcessLogger (adaptador de salida).

Al ser el "contrato" entre entrada y salida, cualquier cambio aquí
impacta toda la cadena. Por eso es un modelo de dominio y no un dict.
"""

from dataclasses import dataclass

from src.domain.models.info_cuenta import InfoCuenta
from src.domain.models.movimiento import Movimiento
from src.domain.models.resumen import Resumen


@dataclass(frozen=True)
class ResultadoParseo:
    """Resultado completo del parseo de un estado de cuenta bancario."""

    info_cuenta: InfoCuenta
    """Información de la cuenta (banco, número, moneda, etc.)."""

    movimientos: list[Movimiento]
    """Lista de movimientos extraídos, ordenados por fecha."""

    resumen: Resumen
    """Totales calculados a partir de los movimientos."""

    año: int
    """Año del estado de cuenta. Se extrae del periodo o de las fechas
    de los movimientos."""

    mes: int
    """Mes del estado de cuenta (1-12). Mismo origen que año."""

    archivo_origen: str
    """Nombre del archivo original que se parseó. Se guarda para
    trazabilidad en la bitácora y en caso de errores."""

    @property
    def periodo(self) -> str:
        """Devuelve el periodo como string 'YYYY-MM'.

        Útil para agrupar y ordenar estados de cuenta cronológicamente
        en la fase de consolidación.
        """
        return f"{self.año:04d}-{self.mes:02d}"

    def __post_init__(self) -> None:
        """Validaciones al crear la instancia."""
        if not 1 <= self.mes <= 12:
            raise ValueError(f"Mes fuera de rango: {self.mes}. Debe ser 1-12.")
        if self.año < 2000 or self.año > 2100:
            raise ValueError(f"Año fuera de rango razonable: {self.año}")
