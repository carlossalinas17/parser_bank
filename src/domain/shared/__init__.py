"""
Utilidades compartidas del dominio.

Estas funciones son usadas por múltiples bank parsers y no dependen
de ninguna librería externa. Solo operan sobre tipos nativos de Python.

Uso:
    from src.domain.shared.money import parse_money, parse_money_safe
    from src.domain.shared.month_map import month_to_number, month_to_int
    from src.domain.shared.date_parser import parse_bank_date
    from src.domain.shared.text_cleaner import clean_whitespace, clean_pdf_text
"""
