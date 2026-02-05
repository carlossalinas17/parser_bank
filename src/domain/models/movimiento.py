"""
Modelo de dominio: Movimiento bancario.

Un Movimiento representa una operación individual en un estado de cuenta:
un depósito, un retiro, una comisión, una transferencia, etc.

Decisiones de diseño:
- Se usa `Decimal` para montos porque `float` tiene errores de redondeo
  con dinero. Ejemplo: float(0.1) + float(0.2) = 0.30000000000000004.
  Con Decimal: Decimal("0.1") + Decimal("0.2") = Decimal("0.3").
- Se usa `date` (no `str`) para la fecha porque permite ordenar y comparar
  movimientos cronológicamente sin parsear strings cada vez.
- `retiro` y `deposito` son mutuamente excluyentes: si uno tiene valor,
  el otro es 0. Esto refleja cómo funcionan los estados de cuenta reales.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Movimiento:
    """Representa un movimiento bancario individual.

    frozen=True hace que la instancia sea inmutable después de crearla.
    ¿Por qué inmutable? Porque un movimiento ya parseado no debería cambiar.
    Si necesitas "modificarlo", creas uno nuevo. Esto previene bugs donde
    un componente modifica un movimiento que otro componente ya estaba usando.
    """

    # --- Campos obligatorios ---

    fecha: date
    """Fecha del movimiento. Tipo `date` (no string) para poder ordenar."""

    concepto: str
    """Descripción del movimiento tal como aparece en el estado de cuenta.
    Puede incluir múltiples líneas concatenadas si el banco usa varias líneas
    para describir un solo movimiento."""

    referencia: str
    """Referencia bancaria, folio, o número de transacción.
    Cadena vacía si el banco no proporciona referencia."""

    retiro: Decimal
    """Monto del retiro. Decimal("0") si el movimiento es un depósito.
    Siempre >= 0 (nunca negativo)."""

    deposito: Decimal
    """Monto del depósito. Decimal("0") si el movimiento es un retiro.
    Siempre >= 0 (nunca negativo)."""

    # --- Propiedades derivadas ---

    @property
    def tipo(self) -> str:
        """Devuelve 'retiro' o 'deposito' según cuál tenga valor.

        ¿Por qué propiedad y no campo? Porque se deriva de retiro/deposito,
        y guardarlo como campo crearía el riesgo de que alguien ponga
        tipo='deposito' pero deposito=0, lo cual sería inconsistente.
        """
        if self.retiro > Decimal("0"):
            return "retiro"
        return "deposito"

    @property
    def monto(self) -> Decimal:
        """Devuelve el monto del movimiento (el que sea distinto de cero).

        Útil cuando no importa si es retiro o depósito, solo el valor.
        """
        return self.retiro if self.retiro > Decimal("0") else self.deposito

    def __post_init__(self) -> None:
        """Validaciones que se ejecutan automáticamente al crear la instancia.

        ¿Por qué validar aquí? Porque queremos que sea imposible crear un
        Movimiento inválido. Si alguien pasa un monto negativo o ambos
        retiro y depósito con valor, falla inmediatamente en lugar de
        propagar el error hasta la generación del Excel.
        """
        if self.retiro < Decimal("0"):
            raise ValueError(f"retiro no puede ser negativo: {self.retiro}")
        if self.deposito < Decimal("0"):
            raise ValueError(f"deposito no puede ser negativo: {self.deposito}")
        if self.retiro > Decimal("0") and self.deposito > Decimal("0"):
            raise ValueError(
                f"Un movimiento no puede ser retiro ({self.retiro}) "
                f"y depósito ({self.deposito}) al mismo tiempo"
            )
