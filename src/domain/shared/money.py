"""
Utilidades para manejo de montos monetarios.

CONTEXTO DEL PROBLEMA:
En el código original, la función `limpiar_monto` estaba duplicada en 14
de 17 archivos. Peor aún, había inconsistencias peligrosas:

- 12 extractores usaban `float` (impreciso para dinero):
    float("1234567.89") puede perder centavos en sumas acumuladas.

- 2 extractores usaban `Decimal` (correcto):
    Decimal("1234567.89") mantiene precisión exacta.

- Algunos retornaban 0.0 silenciosamente ante errores, enmascarando
  datos corruptos que deberían haber sido reportados.

SOLUCIÓN:
Una sola función que:
1. Siempre devuelve Decimal (precisión monetaria garantizada).
2. Maneja todos los formatos encontrados en estados de cuenta mexicanos:
   "$1,234,567.89", "1234567.89", "1,234.56", "-1,234.56", etc.
3. Lanza excepción clara ante valores no parseables (en vez de enmascarar).
4. Ofrece una variante "segura" (parse_money_safe) que retorna Decimal("0")
   para los casos donde un 0 es aceptable (como campos opcionales).
"""

import re
from decimal import Decimal, InvalidOperation


def parse_money(text: str) -> Decimal:
    """Convierte un texto con formato monetario a Decimal.

    Maneja todos los formatos encontrados en estados de cuenta mexicanos:
    - Con símbolo: "$1,234.56"
    - Sin símbolo: "1,234.56"
    - Sin comas: "1234.56"
    - Negativo: "-1,234.56"
    - Con espacios: " $ 1,234.56 "
    - Espacios dentro del monto (OCR): "1,234 . 56" → "1234.56"

    Args:
        text: Texto que representa un monto monetario.

    Returns:
        Decimal con el valor numérico. Siempre con precisión exacta.

    Raises:
        ValueError: Si el texto no se puede convertir a un monto válido.
                    El mensaje incluye el valor original para debugging.

    Ejemplos:
        >>> parse_money("$1,234.56")
        Decimal('1234.56')
        >>> parse_money("-1,234.56")
        Decimal('-1234.56')
        >>> parse_money("0.00")
        Decimal('0.00')
    """
    if not isinstance(text, str):
        raise TypeError(f"parse_money espera str, recibió {type(text).__name__}")
    if not text.strip():
        raise ValueError("El texto del monto está vacío")

    # Paso 1: Eliminar caracteres no numéricos excepto punto, coma, guion
    # ¿Por qué? Porque los OCR a veces insertan espacios dentro del número:
    # "1,234 . 56" debe convertirse en "1234.56"
    cleaned = text.strip()

    # Quitar símbolo de moneda y espacios
    cleaned = cleaned.replace("$", "").replace(" ", "").strip()

    # Quitar comas de miles
    cleaned = cleaned.replace(",", "")

    # Paso 2: Validar que quede algo parseable
    if not cleaned or cleaned == "-":
        raise ValueError(f"No se pudo extraer un monto de: '{text}'")

    # Paso 3: Convertir a Decimal
    try:
        result = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"No se pudo convertir a monto: '{text}' (limpio: '{cleaned}')")

    return result


def parse_money_safe(text: str) -> Decimal:
    """Versión "segura" de parse_money que retorna Decimal("0") ante errores.

    ¿Cuándo usar esta en lugar de parse_money?
    - Campos opcionales donde un 0 es un valor válido (por ejemplo, el campo
      de "depósito" en un movimiento que es retiro).
    - Valores que pueden estar vacíos o contener '-' como indicador de "nada".

    ¿Cuándo NO usarla?
    - Cuando un monto de 0 podría enmascarar un error real (por ejemplo,
      el total de depósitos del resumen).

    Ejemplos:
        >>> parse_money_safe("$1,234.56")
        Decimal('1234.56')
        >>> parse_money_safe("")
        Decimal('0')
        >>> parse_money_safe("-")
        Decimal('0')
        >>> parse_money_safe("abc")
        Decimal('0')
    """
    if not text or text.strip() in ("", "-", "N/A", "n/a"):
        return Decimal("0")

    try:
        return parse_money(text)
    except ValueError:
        return Decimal("0")


def format_money(amount: Decimal) -> str:
    """Formatea un Decimal como string monetario legible.

    Útil para logging y para la columna de montos en el Excel.

    Ejemplos:
        >>> format_money(Decimal("1234567.89"))
        '$1,234,567.89'
        >>> format_money(Decimal("0"))
        '$0.00'
    """
    # quantize asegura siempre 2 decimales
    amount = amount.quantize(Decimal("0.01"))
    # format con comas de miles
    if amount < 0:
        return f"-${abs(amount):,.2f}"
    return f"${amount:,.2f}"


def is_money_string(text: str) -> bool:
    """Detecta si un texto parece ser un monto monetario.

    Útil en los parsers para distinguir montos de texto normal.
    Busca patrones como: 1,234.56, $1234.56, 0.00, etc.

    Ejemplos:
        >>> is_money_string("1,234.56")
        True
        >>> is_money_string("PAGO NOMINA")
        False
        >>> is_money_string("0.00")
        True
    """
    if not text or not text.strip():
        return False
    cleaned = text.strip().replace("$", "").replace(",", "").replace(" ", "")
    return bool(re.match(r"^-?\d+\.\d{2}$", cleaned))
