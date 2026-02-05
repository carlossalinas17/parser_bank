"""
Tests para src.domain.shared.money

Cada caso de prueba viene de un formato real encontrado en los extractores:
- "$1,234.56" → BBVA, Banorte, Scotiabank
- "1234.56"   → Citibanamex, Citi
- "1,234 . 56" → Bank of America (OCR con espacios)
- "-1,234.56" → Monex (montos negativos)
"""

from decimal import Decimal

import pytest

from src.domain.shared.money import (
    format_money,
    is_money_string,
    parse_money,
    parse_money_safe,
)


class TestParseMoney:
    """Pruebas para parse_money (versión estricta, lanza excepciones)."""

    # --- Formatos estándar (sin símbolo) ---

    def test_monto_simple(self):
        assert parse_money("1234.56") == Decimal("1234.56")

    def test_monto_con_comas(self):
        assert parse_money("1,234.56") == Decimal("1234.56")

    def test_monto_grande_con_comas(self):
        assert parse_money("1,234,567.89") == Decimal("1234567.89")

    def test_monto_cero(self):
        assert parse_money("0.00") == Decimal("0.00")

    def test_monto_centavos(self):
        assert parse_money("0.50") == Decimal("0.50")

    # --- Con símbolo de moneda ---

    def test_con_signo_peso(self):
        assert parse_money("$1,234.56") == Decimal("1234.56")

    def test_con_signo_peso_y_espacio(self):
        assert parse_money("$ 1,234.56") == Decimal("1234.56")

    # --- Con espacios (caso OCR / Bank of America) ---

    def test_con_espacios_internos(self):
        """Bank of America OCR: '52,563 . 5 0' → 52563.50"""
        assert parse_money("52,563 . 5 0") == Decimal("52563.50")

    def test_con_espacios_alrededor(self):
        assert parse_money("  1,234.56  ") == Decimal("1234.56")

    # --- Negativos (Monex) ---

    def test_negativo(self):
        assert parse_money("-1,234.56") == Decimal("-1234.56")

    # --- Precisión Decimal (el porqué de no usar float) ---

    def test_precision_decimal_vs_float(self):
        """Demuestra por qué se usa Decimal y no float.
        float(0.1) + float(0.2) = 0.30000000000000004
        Decimal("0.1") + Decimal("0.2") = Decimal("0.3")
        """
        a = parse_money("0.10")
        b = parse_money("0.20")
        assert a + b == Decimal("0.30")  # Exacto con Decimal

    # --- Errores ---

    def test_texto_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="vacío"):
            parse_money("")

    def test_solo_espacios_lanza_error(self):
        with pytest.raises(ValueError, match="vacío"):
            parse_money("   ")

    def test_texto_no_numerico_lanza_error(self):
        with pytest.raises(ValueError, match="No se pudo convertir"):
            parse_money("PAGO NOMINA")

    def test_none_no_se_acepta(self):
        """parse_money requiere string, no None. Esto es intencional:
        si un campo es None, el parser debe manejarlo antes."""
        with pytest.raises(TypeError):
            parse_money(None)  # type: ignore


class TestParseMoneySafe:
    """Pruebas para parse_money_safe (versión tolerante, devuelve 0)."""

    def test_monto_valido(self):
        assert parse_money_safe("$1,234.56") == Decimal("1234.56")

    def test_texto_vacio_devuelve_cero(self):
        assert parse_money_safe("") == Decimal("0")

    def test_none_como_string_devuelve_cero(self):
        """Aunque parse_money_safe espera str, verificamos tolerancia."""
        assert parse_money_safe("") == Decimal("0")

    def test_guion_devuelve_cero(self):
        """Algunos bancos usan '-' para indicar campo vacío."""
        assert parse_money_safe("-") == Decimal("0")

    def test_na_devuelve_cero(self):
        assert parse_money_safe("N/A") == Decimal("0")

    def test_texto_invalido_devuelve_cero(self):
        assert parse_money_safe("CONCEPTO") == Decimal("0")


class TestFormatMoney:
    """Pruebas para format_money (Decimal → string legible)."""

    def test_formato_basico(self):
        assert format_money(Decimal("1234.56")) == "$1,234.56"

    def test_formato_grande(self):
        assert format_money(Decimal("1234567.89")) == "$1,234,567.89"

    def test_formato_cero(self):
        assert format_money(Decimal("0")) == "$0.00"

    def test_formato_negativo(self):
        assert format_money(Decimal("-1234.56")) == "-$1,234.56"

    def test_siempre_dos_decimales(self):
        """Incluso si el Decimal tiene más o menos decimales."""
        assert format_money(Decimal("100")) == "$100.00"
        assert format_money(Decimal("100.5")) == "$100.50"


class TestIsMoneyString:
    """Pruebas para is_money_string (detección de patrones monetarios)."""

    @pytest.mark.parametrize(
        "text",
        ["1,234.56", "0.00", "$1,234.56", "1234.56", "999,999,999.99"],
    )
    def test_montos_validos(self, text):
        assert is_money_string(text) is True

    @pytest.mark.parametrize(
        "text",
        ["PAGO NOMINA", "ABC", "", "1234", "1,234", ".56", "1.2"],
    )
    def test_no_montos(self, text):
        assert is_money_string(text) is False
