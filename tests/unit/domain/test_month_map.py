"""
Tests para src.domain.shared.month_map

Cada test case corresponde a un formato de mes real encontrado en los
extractores originales. Si algún formato nuevo aparece en un banco,
se agrega aquí PRIMERO (Red), luego se implementa (Green).
"""

import pytest

from src.domain.shared.month_map import month_to_int, month_to_number


class TestMonthToNumber:
    """Pruebas para month_to_number (devuelve string '01'-'12')."""

    # --- Abreviaturas español (3 letras, mayúsculas) ---
    # Estos son los más comunes. Usados por: BBVA, Banorte, Santander,
    # Scotiabank, Monex, Sabadell, Banregio, Inbursa, Intercam, Bankaool.

    @pytest.mark.parametrize(
        "input_month, expected",
        [
            ("ENE", "01"),
            ("FEB", "02"),
            ("MAR", "03"),
            ("ABR", "04"),
            ("MAY", "05"),
            ("JUN", "06"),
            ("JUL", "07"),
            ("AGO", "08"),
            ("SEP", "09"),
            ("OCT", "10"),
            ("NOV", "11"),
            ("DIC", "12"),
        ],
    )
    def test_abreviaturas_español_mayusculas(self, input_month, expected):
        assert month_to_number(input_month) == expected

    # --- Abreviaturas inglés (3 letras, mayúsculas) ---
    # Usados por: Citibanamex (JAN, FEB, ..., DEC), Bank of America, Citi.

    @pytest.mark.parametrize(
        "input_month, expected",
        [
            ("JAN", "01"),
            ("APR", "04"),
            ("AUG", "08"),
            ("DEC", "12"),
        ],
    )
    def test_abreviaturas_ingles_mayusculas(self, input_month, expected):
        assert month_to_number(input_month) == expected

    # --- Case-insensitive ---
    # El código original tenía variantes: 'Ene' (Monex), 'ene' (nunca),
    # 'ENE' (mayoría). Nuestro month_map normaliza a mayúsculas.

    @pytest.mark.parametrize(
        "input_month, expected",
        [
            ("ene", "01"),
            ("Ene", "01"),
            ("ENE", "01"),
            ("oct", "10"),
            ("Oct", "10"),
            ("jan", "01"),
            ("Jan", "01"),
        ],
    )
    def test_case_insensitive(self, input_month, expected):
        assert month_to_number(input_month) == expected

    # --- Nombres completos ---
    # No encontrados en el código actual pero soportados por robustez.

    @pytest.mark.parametrize(
        "input_month, expected",
        [
            ("ENERO", "01"),
            ("DICIEMBRE", "12"),
            ("SEPTEMBER", "09"),
            ("JANUARY", "01"),
        ],
    )
    def test_nombres_completos(self, input_month, expected):
        assert month_to_number(input_month) == expected

    # --- Con espacios (strip) ---
    # pdfplumber a veces agrega espacios al extraer texto.

    def test_con_espacios_alrededor(self):
        assert month_to_number("  ENE  ") == "01"
        assert month_to_number("\tDIC\n") == "12"

    # --- Abreviatura SEPT (4 letras) ---
    # Encontrado en: extractor_banorte_final.py

    def test_sept_cuatro_letras(self):
        assert month_to_number("SEPT") == "09"

    # --- Errores ---

    def test_mes_invalido_lanza_valueerror(self):
        with pytest.raises(ValueError, match="Mes no reconocido"):
            month_to_number("XYZ")

    def test_string_vacio_lanza_valueerror(self):
        with pytest.raises(ValueError, match="Mes no reconocido"):
            month_to_number("")

    def test_numero_como_string_lanza_valueerror(self):
        """Los números no son meses válidos; se espera texto."""
        with pytest.raises(ValueError, match="Mes no reconocido"):
            month_to_number("01")


class TestMonthToInt:
    """Pruebas para month_to_int (devuelve int 1-12)."""

    def test_devuelve_entero(self):
        result = month_to_int("ENE")
        assert result == 1
        assert isinstance(result, int)

    def test_diciembre_es_12(self):
        assert month_to_int("DIC") == 12

    def test_ingles_funciona(self):
        assert month_to_int("JAN") == 1
        assert month_to_int("DEC") == 12

    def test_error_propaga_desde_month_to_number(self):
        with pytest.raises(ValueError):
            month_to_int("INVALIDO")
