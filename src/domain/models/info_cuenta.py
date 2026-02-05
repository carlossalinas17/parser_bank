"""
Modelo de dominio: Información de la cuenta bancaria.

Se extrae típicamente de la primera página del estado de cuenta.
Contiene los datos que identifican la cuenta y que se repiten en
cada fila del Excel de salida (columnas Banco, Cuenta, Moneda).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class InfoCuenta:
    """Información de la cuenta bancaria.

    frozen=True porque la info de cuenta no cambia durante el procesamiento
    de un estado de cuenta.
    """

    banco: str
    """Nombre del banco. Ejemplo: 'BBVA', 'BANORTE', 'SCOTIABANK'.
    Se normaliza a mayúsculas para consistencia en el Excel de salida."""

    cuenta: str
    """Número de cuenta. Se guarda como string (no int) porque:
    - Puede tener ceros iniciales (ej: '0012345678')
    - Puede tener guiones (ej: '12-34567890-1' en Santander)
    - Puede ser CLABE de 18 dígitos que excede int32
    """

    moneda: str
    """Código de moneda. Valores esperados: 'MXN', 'USD'.
    Se normaliza a mayúsculas."""

    rfc: str = ""
    """RFC de la empresa titular. Vacío si no aparece en el estado de cuenta.
    Algunos bancos (Sabadell, Monex) lo incluyen en la primera página."""

    clabe: str = ""
    """CLABE interbancaria. Vacío si no aparece.
    Algunos bancos (Bankaool, Monex) la incluyen."""

    def __post_init__(self) -> None:
        """Validaciones al crear la instancia."""
        if not self.banco:
            raise ValueError("El nombre del banco no puede estar vacío")
        if not self.cuenta:
            raise ValueError("El número de cuenta no puede estar vacío")
        if self.moneda not in ("MXN", "USD", "EUR"):
            raise ValueError(f"Moneda no reconocida: '{self.moneda}'. Esperado: MXN, USD o EUR")
