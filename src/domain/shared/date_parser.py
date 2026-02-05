"""
Conversión unificada de fechas bancarias.

CONTEXTO DEL PROBLEMA:
Cada banco usa un formato de fecha diferente en sus estados de cuenta.
En el código original, cada extractor implementaba su propia conversión,
con resultados inconsistentes:

- BBVA:           "05/OCT" → "05/10/2021" (año hardcodeado)
- Citibanamex:    "05 OCT" → "05/10/24" (año hardcodeado "24")
- Santander:      "05-oct" → "05/10/24"
- JP Morgan:      "05OCT24" → "05/10/2024"
- Bank of America: "05OCT24" → "05/10/2024"
- Intercam:       "5" (solo día) + año/mes del periodo
- Monex:          "05/Oct" → "05/10/2025"

SOLUCIÓN:
Un parser centralizado que:
1. Acepta todos los formatos encontrados.
2. Siempre devuelve un objeto `date` de Python (no string).
3. Requiere el año explícitamente cuando no está en el texto.
4. Lanza errores claros cuando no puede parsear.
"""

import re
from datetime import date

from src.domain.shared.month_map import month_to_int


def parse_bank_date(
    date_text: str,
    year: int | None = None,
    month: int | None = None,
) -> date:
    """Parsea una fecha de estado de cuenta bancario a un objeto date.

    Soporta los siguientes formatos (detectados automáticamente):

    Con mes texto:
        "05/OCT"        → necesita year
        "05/OCT/24"     → año de 2 dígitos
        "05/OCT/2024"   → año de 4 dígitos
        "05 OCT"        → necesita year
        "05 OCT 24"     → año de 2 dígitos
        "05OCT24"       → formato compacto (Bank of America, JP Morgan)
        "05-Oct-2024"   → con guiones

    Solo día:
        "5" o "05"      → necesita year Y month (Intercam)

    Formato numérico:
        "05/10/24"      → dd/mm/yy
        "05/10/2024"    → dd/mm/yyyy
        "10/05/24"      → NO soportado (mm/dd/yy) para evitar ambigüedad

    Args:
        date_text: Texto de la fecha tal como aparece en el estado de cuenta.
        year: Año a usar cuando no está incluido en el texto. Si el texto
              tiene año, este parámetro se ignora.
        month: Mes a usar cuando solo se tiene el día (caso Intercam).

    Returns:
        Objeto date de Python.

    Raises:
        ValueError: Si no se puede parsear o faltan datos (año sin pasar, etc.)

    Ejemplos:
        >>> parse_bank_date("05/OCT", year=2024)
        date(2024, 10, 5)
        >>> parse_bank_date("05OCT24")
        date(2024, 10, 5)
        >>> parse_bank_date("5", year=2024, month=10)
        date(2024, 10, 5)
    """
    text = date_text.strip()

    if not text:
        raise ValueError("El texto de fecha está vacío")

    # --- Caso 1: Solo día (1-2 dígitos) ---
    # Ejemplo: "5", "05", "31"
    # Usado por: Intercam (solo pone el día; mes y año vienen del periodo)
    if re.match(r"^\d{1,2}$", text):
        day = int(text)
        if month is None or year is None:
            raise ValueError(
                f"Fecha '{text}' solo contiene el día. "
                f"Se requieren los parámetros year={year} y month={month}"
            )
        return _build_date(year, month, day, text)

    # --- Caso 2: Formato compacto DDMMMYY (sin separadores) ---
    # Ejemplo: "05OCT24", "12ENE25"
    # Usado por: Bank of America, JP Morgan
    m = re.match(r"^(\d{2})([A-Za-z]{3})(\d{2})$", text)
    if m:
        day = int(m.group(1))
        month_parsed = month_to_int(m.group(2))
        year_parsed = _expand_year(int(m.group(3)))
        return _build_date(year_parsed, month_parsed, day, text)

    # --- Caso 3: DD/MMM, DD/MMM/YY, DD/MMM/YYYY (con separador / o -) ---
    # Ejemplo: "05/OCT", "05/OCT/24", "05-Oct-2024"
    # Usado por: BBVA, Banorte, Monex, Santander, etc.
    m = re.match(r"^(\d{1,2})[/\-\s]+([A-Za-z]{3,})(?:[/\-\s]+(\d{2,4}))?$", text)
    if m:
        day = int(m.group(1))
        month_parsed = month_to_int(m.group(2))
        year_text = m.group(3)

        if year_text:
            year_parsed = _expand_year(int(year_text))
        elif year is not None:
            year_parsed = year
        else:
            raise ValueError(
                f"Fecha '{text}' no incluye año y no se proporcionó " f"el parámetro year"
            )

        return _build_date(year_parsed, month_parsed, day, text)

    # --- Caso 4: DD MMM (espacio como separador, sin año) ---
    # Ejemplo: "05 OCT", "12 ENE"
    # Usado por: Citibanamex
    m = re.match(r"^(\d{1,2})\s+([A-Za-z]{3,})$", text)
    if m:
        day = int(m.group(1))
        month_parsed = month_to_int(m.group(2))
        if year is None:
            raise ValueError(
                f"Fecha '{text}' no incluye año y no se proporcionó " f"el parámetro year"
            )
        return _build_date(year, month_parsed, day, text)

    # --- Caso 5: DD/MM/YY o DD/MM/YYYY (totalmente numérico) ---
    # Ejemplo: "05/10/24", "05/10/2024"
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", text)
    if m:
        day = int(m.group(1))
        month_parsed = int(m.group(2))
        year_parsed = _expand_year(int(m.group(3)))

        if not 1 <= month_parsed <= 12:
            raise ValueError(f"Mes fuera de rango en fecha '{text}': {month_parsed}")

        return _build_date(year_parsed, month_parsed, day, text)

    # --- Caso 6: MM/DD/YY (formato americano, solo Citi USA) ---
    # Ejemplo: "10/05/24" donde 10=mes, 05=día
    # NO lo soportamos por defecto porque es ambiguo con DD/MM/YY.
    # Los parsers de bancos americanos deben usar parse_american_date().

    raise ValueError(
        f"Formato de fecha no reconocido: '{text}'. "
        f"Formatos soportados: DD/MMM, DD/MMM/YY, DDMMMYY, DD/MM/YY, etc."
    )


def parse_american_date(date_text: str) -> date:
    """Parsea fechas en formato americano MM/DD/YY.

    Separado de parse_bank_date para evitar ambigüedad con DD/MM/YY.
    Solo debe usarse en parsers de bancos que explícitamente usan
    formato americano (por ejemplo, Citi USA).

    Args:
        date_text: Fecha en formato MM/DD/YY. Ejemplo: "10/05/24"

    Returns:
        Objeto date.

    Raises:
        ValueError: Si el formato no es MM/DD/YY.
    """
    text = date_text.strip()
    m = re.match(r"^(\d{2})/(\d{2})/(\d{2})$", text)
    if not m:
        raise ValueError(f"Formato americano esperado MM/DD/YY, recibido: '{text}'")

    month = int(m.group(1))
    day = int(m.group(2))
    year = _expand_year(int(m.group(3)))
    return _build_date(year, month, day, text)


# ============================================================
# FUNCIONES INTERNAS (prefijo _ = no exportadas)
# ============================================================


def _expand_year(year_short: int) -> int:
    """Expande un año de 2 dígitos a 4 dígitos.

    Regla: 00-49 → 2000-2049, 50-99 → 1950-1999.
    Si ya tiene 4 dígitos, lo devuelve tal cual.

    ¿Por qué 50 como corte? Porque los estados de cuenta que procesamos
    son de los últimos ~25 años (2000-2026). Un año "50" sería 1950,
    que no es un caso real para este proyecto, pero es la convención
    estándar de ventana de 100 años.
    """
    if year_short >= 100:
        return year_short  # Ya tiene 4 dígitos
    if year_short < 50:
        return 2000 + year_short
    return 1900 + year_short


def _build_date(year: int, month: int, day: int, original_text: str) -> date:
    """Construye un objeto date con validación.

    ¿Por qué una función separada? Para centralizar el manejo de errores
    de fechas inválidas (por ejemplo, 31 de febrero) y dar un mensaje
    que incluya el texto original para debugging.
    """
    try:
        return date(year, month, day)
    except ValueError as e:
        raise ValueError(
            f"Fecha inválida construida de '{original_text}': "
            f"año={year}, mes={month}, día={day} — {e}"
        )
