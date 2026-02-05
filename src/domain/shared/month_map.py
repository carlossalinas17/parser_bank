"""
Mapeo unificado de nombres de meses a números.

CONTEXTO DEL PROBLEMA:
En el código original, este diccionario estaba copiado y pegado en 15 de 17
archivos, con variaciones inconsistentes:
- Algunos solo tenían español: {'ENE': '01', 'FEB': '02', ...}
- Otros mezclaban español e inglés: {'ENE': '01', 'JAN': '01', ...}
- Otros usaban capitalización: {'Ene': '01', 'Feb': '02', ...}

Esto causaba que si un estado de cuenta usaba 'ENERO' (nombre completo),
solo algunos extractores lo reconocían. Para agregar soporte, había que
modificar 15 archivos.

SOLUCIÓN:
Un solo diccionario exhaustivo que cubre TODAS las variantes encontradas
en los estados de cuenta mexicanos:
- Abreviaturas de 3 letras en español: ENE, FEB, MAR, ...
- Abreviaturas de 3 letras en inglés: JAN, FEB, MAR, ...
- Nombres completos en español: ENERO, FEBRERO, MARZO, ...
- Nombres completos en inglés: JANUARY, FEBRUARY, MARCH, ...

El lookup siempre es case-insensitive (se normaliza a mayúsculas).
"""

# Diccionario principal: clave → número de mes como string '01'-'12'.
# Se usa string porque el formato de salida es 'dd/mm/yy' (texto).
_MONTH_MAP: dict[str, str] = {
    # --- Español: abreviaturas de 3 letras ---
    "ENE": "01",
    "FEB": "02",
    "MAR": "03",
    "ABR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AGO": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DIC": "12",
    # --- Español: abreviatura de 4 letras (Septiembre) ---
    "SEPT": "09",
    # --- Español: nombres completos ---
    "ENERO": "01",
    "FEBRERO": "02",
    "MARZO": "03",
    "ABRIL": "04",
    "MAYO": "05",
    "JUNIO": "06",
    "JULIO": "07",
    "AGOSTO": "08",
    "SEPTIEMBRE": "09",
    "OCTUBRE": "10",
    "NOVIEMBRE": "11",
    "DICIEMBRE": "12",
    # --- Inglés: abreviaturas de 3 letras ---
    "JAN": "01",
    # FEB ya está arriba (coincide)
    # MAR ya está arriba (coincide)
    "APR": "04",
    # MAY ya está arriba (coincide)
    # JUN ya está arriba (coincide)
    # JUL ya está arriba (coincide)
    "AUG": "08",
    # SEP ya está arriba (coincide)
    # OCT ya está arriba (coincide)
    # NOV ya está arriba (coincide)
    "DEC": "12",
    # --- Inglés: nombres completos ---
    "JANUARY": "01",
    "FEBRUARY": "02",
    "MARCH": "03",
    "APRIL": "04",
    # MAY/MAYO coinciden
    "JUNE": "06",
    "JULY": "07",
    "AUGUST": "08",
    "SEPTEMBER": "09",
    "OCTOBER": "10",
    "NOVEMBER": "11",
    "DECEMBER": "12",
}


def month_to_number(month_name: str) -> str:
    """Convierte un nombre de mes (en cualquier formato) a su número '01'-'12'.

    El lookup es case-insensitive: 'ene', 'ENE', 'Ene' → '01'.

    Args:
        month_name: Nombre o abreviatura del mes. Ejemplos: 'ENE', 'Enero',
                    'JAN', 'January', 'AGO', 'Aug'.

    Returns:
        String de 2 dígitos: '01' a '12'.

    Raises:
        ValueError: Si el nombre no se reconoce. Incluye el valor recibido
                    en el mensaje para facilitar debugging.

    Ejemplos:
        >>> month_to_number("ENE")
        '01'
        >>> month_to_number("January")
        '01'
        >>> month_to_number("ago")
        '08'
    """
    normalized = month_name.strip().upper()
    result = _MONTH_MAP.get(normalized)
    if result is None:
        raise ValueError(
            f"Mes no reconocido: '{month_name}'. "
            f"Valores válidos: {sorted(set(_MONTH_MAP.values()))}"
        )
    return result


def month_to_int(month_name: str) -> int:
    """Igual que month_to_number pero devuelve int.

    Útil cuando se necesita el mes como entero para construir objetos date.

    Ejemplos:
        >>> month_to_int("ENE")
        1
        >>> month_to_int("DIC")
        12
    """
    return int(month_to_number(month_name))
