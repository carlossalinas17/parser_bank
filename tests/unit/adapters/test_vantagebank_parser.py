"""
Tests para el parser de Vantage Bank.

Diferencias clave que estos tests validan vs Santander/Scotiabank:
- Fecha americana MM-DD (mes primero, sin año).
- Formato de línea invertido: CONCEPTO FECHA MONTO.
- Clasificación por SECCIÓN del PDF (no por keywords).
- Moneda default USD (banco texano).
- Sin signo $ en los montos.
- Cuenta de 9 dígitos.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.input.bank_parsers.vantagebank_parser import VantageBankParser
from src.domain.exceptions import ParseError
from src.domain.models.page_text import PageText


class TestVantageBankParser:
    """Tests unitarios para VantageBankParser."""

    @pytest.fixture
    def parser(self):
        return VantageBankParser()

    # === Helpers ===

    def _make_page(
        self,
        sections: dict[str, list[str]] | None = None,
        header: str | None = None,
    ) -> PageText:
        """Crea una página simulada de Vantage Bank.

        Args:
            sections: Dict de nombre_seccion → líneas de movimientos.
                Ejemplo: {"DEPOSITOS": ["WIRE IN 1-15 50,000.00"]}
            header: Texto del encabezado.
        """
        if header is None:
            header = (
                "Vantage Bank Texas\n"
                "Account Statement\n"
                "cuenta 107072718\n"
                "Period: Dec 1, 2024 through Dec 31, 2024\n"
                "USD\n"
            )

        parts = [header]

        if sections:
            for section_name, lines in sections.items():
                parts.append(section_name)
                parts.extend(lines)
                parts.append("Total")

        text = "\n".join(parts)
        return PageText(page_num=1, text=text)

    # === Tests de retiros (sección DEBITOS/OTROS DEBITOS) ===

    def test_retiro_seccion_otros_debitos(self, parser):
        """Movimiento en sección 'OTROS DEBITOS' → retiro."""
        page = self._make_page(
            sections={
                "OTROS DEBITOS": ["INACTIVE ACCOUNT FEE 12-31 10.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("10.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

    def test_retiro_seccion_debitos(self, parser):
        """Movimiento en sección 'DEBITOS' → retiro."""
        page = self._make_page(
            sections={
                "DEBITOS": ["WIRE TRANSFER OUT 12-15 5,000.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("5000.00")

    def test_retiro_seccion_retiros(self, parser):
        """Movimiento en sección 'RETIROS' → retiro."""
        page = self._make_page(
            sections={
                "RETIROS": ["ATM WITHDRAWAL 12-20 500.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("500.00")

    # === Tests de depósitos (sección DEPOSITOS) ===

    def test_deposito_seccion_depositos(self, parser):
        """Movimiento en sección 'DEPOSITOS' → depósito."""
        page = self._make_page(
            sections={
                "DEPOSITOS": ["WIRE TRANSFER IN 12-15 50,000.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("50000.00")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_deposito_seccion_depositos_acento(self, parser):
        """Sección 'DEPÓSITOS' (con acento) → depósito."""
        page = self._make_page(
            sections={
                "DEPÓSITOS": ["CHECK DEPOSIT 12-10 25,000.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("25000.00")

    # === Tests de múltiples secciones ===

    def test_multiples_secciones(self, parser):
        """Depósitos y retiros en secciones diferentes."""
        page = self._make_page(
            sections={
                "DEPOSITOS": [
                    "WIRE TRANSFER IN 12-5 50,000.00",
                    "CHECK DEPOSIT 12-10 25,000.00",
                ],
                "OTROS DEBITOS": [
                    "WIRE TRANSFER OUT 12-15 30,000.00",
                    "INACTIVE ACCOUNT FEE 12-31 10.00",
                ],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 4
        depositos = [m for m in resultado.movimientos if m.deposito > Decimal("0")]
        retiros = [m for m in resultado.movimientos if m.retiro > Decimal("0")]
        assert len(depositos) == 2
        assert len(retiros) == 2

    # === Tests de fecha americana MM-DD ===

    def test_fecha_americana_basica(self, parser):
        """Fecha 12-31 → 31 de diciembre."""
        page = self._make_page(
            sections={
                "DEBITOS": ["SERVICE FEE 12-31 10.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2024, 12, 31)

    def test_fecha_americana_sin_cero(self, parser):
        """Fecha 1-5 → 5 de enero."""
        page = self._make_page(
            header=(
                "Vantage Bank Texas\n"
                "cuenta 107072718\n"
                "Period: Jan 1, 2025 through Jan 31, 2025\n"
                "USD\n"
            ),
            sections={
                "DEBITOS": ["CHARGE 1-5 100.00"],
            },
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2025, 1, 5)

    # === Tests de formato de línea CONCEPTO FECHA MONTO ===

    def test_concepto_extraido_correctamente(self, parser):
        """La descripción (antes de la fecha) es el concepto."""
        page = self._make_page(
            sections={
                "DEBITOS": ["INACTIVE ACCOUNT FEE 12-31 10.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].concepto == "INACTIVE ACCOUNT FEE"

    def test_monto_con_comas(self, parser):
        """Montos con separador de miles: 50,000.00."""
        page = self._make_page(
            sections={
                "DEPOSITOS": ["WIRE IN 12-15 150,000.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].deposito == Decimal("150000.00")

    # === Tests de info de cuenta ===

    def test_extrae_cuenta_9_digitos(self, parser):
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.banco == "VANTAGE_BANK"
        assert resultado.info_cuenta.cuenta == "107072718"

    def test_moneda_default_usd(self, parser):
        """Vantage Bank default es USD."""
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.moneda == "USD"

    def test_moneda_mxn_si_explicita(self, parser):
        """Si el texto dice MXN, se usa MXN."""
        page = self._make_page(
            header=("Vantage Bank\n" "cuenta 107072718\n" "Period: Dec 2024\n" "MXN\n"),
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.moneda == "MXN"

    def test_cuenta_no_encontrada(self, parser):
        page = self._make_page(
            header="Vantage Bank\nPeriod: Dec 2024\nUSD\n",
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.cuenta == "SIN_CUENTA"

    # === Tests de periodo ===

    def test_extrae_año(self, parser):
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2024

    def test_extrae_mes_ingles(self, parser):
        """Detecta mes en inglés del encabezado."""
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.mes == 12  # "Dec" en el encabezado

    # === Tests de secciones ===

    def test_ignora_lineas_fuera_de_seccion(self, parser):
        """Movimientos fuera de una sección se ignoran."""
        page = self._make_page(
            header=(
                "Vantage Bank\n"
                "cuenta 107072718\n"
                "Period: Dec 2024\n"
                "SOME LINE WITH DATE 12-15 999.00\n"
            ),
            sections={
                "DEBITOS": ["REAL MOVEMENT 12-20 100.00"],
            },
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        assert resultado.movimientos[0].concepto == "REAL MOVEMENT"

    def test_seccion_termina_con_total(self, parser):
        """'Total' marca el fin de la sección."""
        page = self._make_page(
            sections={
                "DEBITOS": [
                    "FEE 12-31 10.00",
                ],
                # "Total" se agrega automáticamente por _make_page
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1

    def test_ignora_encabezados_de_seccion(self, parser):
        """Líneas como 'Descripción' o 'Fecha' se ignoran."""
        page = self._make_page(
            sections={
                "DEBITOS": [
                    "Descripción Fecha Monto",
                    "SERVICE FEE 12-31 10.00",
                ],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1

    # === Tests de resumen ===

    def test_calcula_resumen(self, parser):
        page = self._make_page(
            sections={
                "DEPOSITOS": [
                    "WIRE IN 12-5 10,000.00",
                    "CHECK 12-10 5,000.00",
                ],
                "DEBITOS": [
                    "FEE 12-31 200.00",
                ],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.resumen.total_depositos == Decimal("15000.00")
        assert resultado.resumen.total_retiros == Decimal("200.00")
        assert resultado.resumen.num_depositos == 2
        assert resultado.resumen.num_retiros == 1

    # === Tests de Decimal ===

    def test_montos_usan_decimal(self, parser):
        page = self._make_page(
            sections={
                "DEBITOS": ["FEE 12-31 10.50"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert isinstance(mov.retiro, Decimal)

    # === Tests de líneas ignoradas ===

    def test_ignora_lineas_sin_patron(self, parser):
        """Líneas que no matchean CONCEPTO FECHA MONTO se ignoran."""
        page = self._make_page(
            sections={
                "DEBITOS": [
                    "This is just a note",
                    "SERVICE FEE 12-31 10.00",
                    "",
                ],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1

    # === Tests de errores ===

    def test_error_sin_paginas(self, parser):
        with pytest.raises(ParseError, match="No se recibieron"):
            parser.parse([], file_name="test.pdf")

    def test_bank_name(self, parser):
        assert parser.bank_name == "VANTAGE_BANK"

    # === Test no requiere words ===

    def test_funciona_sin_words(self, parser):
        """Vantage Bank NO requiere coordenadas."""
        page = PageText(
            page_num=1,
            text=(
                "Vantage Bank\ncuenta 107072718\n"
                "Period: Dec 2024\nUSD\n"
                "DEBITOS\n"
                "SERVICE FEE 12-31 10.00\n"
                "Total"
            ),
        )
        assert not page.has_words

        resultado = parser.parse([page], file_name="test.pdf")
        assert len(resultado.movimientos) == 1

    # === Test referencia siempre vacía ===

    def test_referencia_vacia(self, parser):
        """Vantage Bank no incluye referencia en los movimientos."""
        page = self._make_page(
            sections={
                "DEBITOS": ["SERVICE FEE 12-31 10.00"],
            }
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].referencia == ""
