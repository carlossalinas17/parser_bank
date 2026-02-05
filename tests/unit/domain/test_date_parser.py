"""
Tests para src.domain.shared.date_parser

Cada formato de fecha corresponde a un banco real:
- "05/OCT"    → BBVA, Banorte, Monex
- "05 OCT"    → Citibanamex
- "05OCT24"   → Bank of America, JP Morgan
- "5"         → Intercam (solo día)
- "05/10/24"  → Formato numérico genérico
"""

from datetime import date

import pytest

from src.domain.shared.date_parser import parse_american_date, parse_bank_date


class TestParseBankDate:
    """Pruebas para parse_bank_date (formato mexicano/estándar)."""

    # --- Formato DD/MMM (sin año) → requiere year ---
    # Usado por: BBVA, Banorte, Monex, Sabadell

    def test_dd_slash_mmm_con_year(self):
        result = parse_bank_date("05/OCT", year=2024)
        assert result == date(2024, 10, 5)

    def test_dd_slash_mmm_sin_year_lanza_error(self):
        with pytest.raises(ValueError, match="no incluye año"):
            parse_bank_date("05/OCT")

    def test_dd_slash_mmm_enero(self):
        assert parse_bank_date("15/ENE", year=2025) == date(2025, 1, 15)

    def test_dd_slash_mmm_diciembre(self):
        assert parse_bank_date("31/DIC", year=2024) == date(2024, 12, 31)

    # --- Formato DD/MMM/YY (con año 2 dígitos) ---
    # Usado por: Santander, algunos Banorte

    def test_dd_slash_mmm_slash_yy(self):
        result = parse_bank_date("05/OCT/24")
        assert result == date(2024, 10, 5)

    def test_dd_slash_mmm_slash_yy_ignora_year_param(self):
        """Si el texto tiene año, el parámetro year se ignora."""
        result = parse_bank_date("05/OCT/24", year=2099)
        assert result == date(2024, 10, 5)

    # --- Formato DD/MMM/YYYY (con año 4 dígitos) ---

    def test_dd_slash_mmm_slash_yyyy(self):
        result = parse_bank_date("05/OCT/2024")
        assert result == date(2024, 10, 5)

    # --- Formato DD MMM (espacio, sin año) ---
    # Usado por: Citibanamex

    def test_dd_space_mmm_con_year(self):
        result = parse_bank_date("05 OCT", year=2024)
        assert result == date(2024, 10, 5)

    def test_dd_space_mmm_ingles(self):
        """Citibanamex usa meses en inglés: JAN, FEB, etc."""
        result = parse_bank_date("05 JAN", year=2024)
        assert result == date(2024, 1, 5)

    def test_dd_space_mmm_sin_year_lanza_error(self):
        with pytest.raises(ValueError, match="no incluye año"):
            parse_bank_date("05 OCT")

    # --- Formato compacto DDMMMYY (sin separadores) ---
    # Usado por: Bank of America, JP Morgan

    def test_ddmmmyy_compacto(self):
        result = parse_bank_date("05OCT24")
        assert result == date(2024, 10, 5)

    def test_ddmmmyy_enero(self):
        assert parse_bank_date("15ENE25") == date(2025, 1, 15)

    def test_ddmmmyy_ingles(self):
        assert parse_bank_date("12AUG24") == date(2024, 8, 12)

    # --- Formato con guiones DD-MMM-YYYY ---

    def test_dd_dash_mmm_dash_yyyy(self):
        result = parse_bank_date("05-Oct-2024")
        assert result == date(2024, 10, 5)

    # --- Solo día (1-2 dígitos) ---
    # Usado por: Intercam (el mes y año vienen del encabezado del periodo)

    def test_solo_dia_con_year_y_month(self):
        result = parse_bank_date("5", year=2024, month=10)
        assert result == date(2024, 10, 5)

    def test_solo_dia_dos_digitos(self):
        result = parse_bank_date("15", year=2024, month=3)
        assert result == date(2024, 3, 15)

    def test_solo_dia_sin_month_lanza_error(self):
        with pytest.raises(ValueError, match="Se requieren"):
            parse_bank_date("5", year=2024)

    def test_solo_dia_sin_year_lanza_error(self):
        with pytest.raises(ValueError, match="Se requieren"):
            parse_bank_date("5", month=10)

    # --- Formato numérico DD/MM/YY ---

    def test_dd_mm_yy_numerico(self):
        result = parse_bank_date("05/10/24")
        assert result == date(2024, 10, 5)

    def test_dd_mm_yyyy_numerico(self):
        result = parse_bank_date("05/10/2024")
        assert result == date(2024, 10, 5)

    # --- Case insensitive ---

    def test_mes_minusculas(self):
        assert parse_bank_date("05/oct", year=2024) == date(2024, 10, 5)

    def test_mes_capitalizado(self):
        assert parse_bank_date("05/Oct", year=2024) == date(2024, 10, 5)

    # --- Expansión de años ---

    def test_año_00_es_2000(self):
        assert parse_bank_date("01/ENE/00") == date(2000, 1, 1)

    def test_año_49_es_2049(self):
        assert parse_bank_date("01/ENE/49") == date(2049, 1, 1)

    def test_año_50_es_1950(self):
        assert parse_bank_date("01/ENE/50") == date(1950, 1, 1)

    # --- Errores ---

    def test_texto_vacio(self):
        with pytest.raises(ValueError, match="vacío"):
            parse_bank_date("")

    def test_formato_no_reconocido(self):
        with pytest.raises(ValueError, match="no reconocido"):
            parse_bank_date("ABCDEFGH")

    def test_fecha_invalida_31_febrero(self):
        with pytest.raises(ValueError, match="Fecha inválida"):
            parse_bank_date("31/FEB/24")

    def test_dia_cero(self):
        with pytest.raises(ValueError, match="Fecha inválida"):
            parse_bank_date("00/ENE/24")


class TestParseAmericanDate:
    """Pruebas para parse_american_date (formato MM/DD/YY)."""

    def test_formato_americano_basico(self):
        """Citi USA usa MM/DD/YY."""
        result = parse_american_date("10/05/24")
        assert result == date(2024, 10, 5)

    def test_enero_primero(self):
        assert parse_american_date("01/01/25") == date(2025, 1, 1)

    def test_formato_invalido_lanza_error(self):
        with pytest.raises(ValueError, match="MM/DD/YY"):
            parse_american_date("5/10/2024")
