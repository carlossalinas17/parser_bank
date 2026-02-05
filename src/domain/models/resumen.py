"""
Modelo de dominio: Resumen de depósitos y retiros.

El Resumen cumple dos funciones:
1. Alimenta la Hoja 1 (RESUMEN) del layout de salida.
2. Permite la comparación entre los totales que reporta el PDF
   y los totales que calculamos nosotros a partir de los movimientos
   parseados. Si hay discrepancia, se registra en la bitácora.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Resumen:
    """Resumen de totales de un estado de cuenta."""

    total_depositos: Decimal
    """Suma de todos los depósitos parseados."""

    total_retiros: Decimal
    """Suma de todos los retiros parseados."""

    num_depositos: int
    """Cantidad de movimientos tipo depósito."""

    num_retiros: int
    """Cantidad de movimientos tipo retiro."""

    saldo_inicial: Decimal | None = None
    """Saldo inicial del periodo. Optional porque no todos los bancos
    lo incluyen en un lugar parseable."""

    saldo_final: Decimal | None = None
    """Saldo final del periodo. Mismo caso que saldo_inicial."""

    @property
    def diferencia_saldos(self) -> Decimal | None:
        """Calcula: saldo_final - saldo_inicial.

        Útil para la validación cruzada:
        saldo_final - saldo_inicial debería ≈ total_depositos - total_retiros.
        Si no coincide, hay movimientos faltantes o duplicados.

        Retorna None si no se tienen ambos saldos.
        """
        if self.saldo_inicial is not None and self.saldo_final is not None:
            return self.saldo_final - self.saldo_inicial
        return None

    @property
    def balance_movimientos(self) -> Decimal:
        """Calcula: total_depositos - total_retiros.

        Es el neto de los movimientos parseados. Debería coincidir
        con diferencia_saldos si el parseo fue completo y correcto.
        """
        return self.total_depositos - self.total_retiros
