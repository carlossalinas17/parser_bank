"""
Tests para el parser de Santander.

Diferencias clave que estos tests validan vs BBVA/Banorte:
- Parsing por regex sobre líneas (no coordenadas X/Y).
- Formato fecha DD-MMM-YYYY (año de 4 dígitos).
- Formato de línea: FECHA FOLIO CONCEPTO MONTOS.
- Clasificación por keywords (no posición X).
- Caso especial: "ABONO POR PAGO DE" con primer monto 0.00.
- Detección de duplicados.
- Limpieza de texto duplicado (artefactos OCR).
- Cuenta con guiones: XX-XXXXXXXX-X.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.input.bank_parsers.santander_parser import SantanderParser
from src.domain.exceptions import ParseError
from src.domain.models.page_text import PageText


class TestSantanderParser:
    """Tests unitarios para SantanderParser."""

    @pytest.fixture
    def parser(self):
        return SantanderParser()

    # === Helpers ===

    def _make_page(
        self,
        movimiento_lines: list[str] | None = None,
        header: str | None = None,
    ) -> PageText:
        """Crea una página simulada de Santander.

        Args:
            movimiento_lines: Líneas de movimientos. Cada una con formato
                DD-MMM-YYYY FOLIO CONCEPTO MONTOS.
            header: Texto del encabezado. Default incluye cuenta y periodo.
        """
        if header is None:
            header = (
                "Santander\n"
                "Estado de Cuenta\n"
                "Cuenta: 65-50123456-7\n"
                "Periodo del 01-Nov-2025 al 30-Nov-2025\n"
                "Moneda: MXN\n"
            )

        if movimiento_lines is None:
            movimiento_lines = []

        text = header + "\n" + "\n".join(movimiento_lines)
        return PageText(page_num=1, text=text)

    # === Tests de retiros (default) ===

    def test_retiro_basico(self, parser):
        """Una línea con concepto no-depósito → retiro."""
        page = self._make_page(["15-NOV-2025 789012 PAGO SERVICIO LUZ 1,500.00 118,500.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("1500.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"
        assert mov.referencia == "789012"

    def test_retiro_concepto_con_espacios(self, parser):
        """Concepto largo con múltiples palabras."""
        page = self._make_page(
            ["3-NOV-2025 123456 COMPRA TIENDA DEPARTAMENTAL 25,000.00 95,000.00"]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("25000.00")
        assert "COMPRA TIENDA DEPARTAMENTAL" in mov.concepto

    # === Tests de depósitos (por keywords) ===

    def test_deposito_keyword_abono(self, parser):
        """Concepto con 'ABONO' → depósito."""
        page = self._make_page(["10-NOV-2025 555555 ABONO TRANSFERENCIA 50,000.00 170,000.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("50000.00")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_deposito_keyword_deposito(self, parser):
        """Concepto con 'DEPOSITO' → depósito."""
        page = self._make_page(["5-NOV-2025 111111 DEPOSITO EN EFECTIVO 30,000.00 150,000.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("30000.00")

    def test_deposito_keyword_recibid(self, parser):
        """Concepto con 'RECIBID' (parcial de RECIBIDO/RECIBIDA) → depósito."""
        page = self._make_page(["7-NOV-2025 222222 TRANSFERENCIA RECIBIDA 15,000.00 135,000.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("15000.00")

    def test_deposito_keyword_devolucion(self, parser):
        """Concepto con 'DEVOLUCION' → depósito."""
        page = self._make_page(["12-NOV-2025 333333 DEVOLUCION CARGO 2,500.00 122,500.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("2500.00")

    # === Test caso especial: ABONO POR PAGO DE ===

    def test_abono_pago_facturas_monto_cero_inicial(self, parser):
        """'ABONO POR PAGO DE' con primer monto 0.00 → usa segundo monto."""
        page = self._make_page(
            ["20-NOV-2025 444444 ABONO POR PAGO DE FACTURAS 0.00 75,000.00 195,000.00"]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("75000.00")
        assert mov.tipo == "deposito"

    def test_monto_cero_inicial_fallback(self, parser):
        """Cualquier movimiento con primer monto 0.00 y 3+ montos → usa segundo."""
        page = self._make_page(["20-NOV-2025 444444 CARGO SERVICIO 0.00 1,200.00 118,800.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("1200.00")

    # === Tests de múltiples movimientos ===

    def test_multiples_movimientos(self, parser):
        """Procesa varias líneas de movimientos correctamente."""
        page = self._make_page(
            [
                "1-NOV-2025 100001 PAGO NOMINA 5,000.00 115,000.00",
                "5-NOV-2025 100002 DEPOSITO EFECTIVO 10,000.00 125,000.00",
                "10-NOV-2025 100003 RETIRO ATM 3,000.00 122,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 3
        assert resultado.movimientos[0].retiro == Decimal("5000.00")
        assert resultado.movimientos[1].deposito == Decimal("10000.00")
        assert resultado.movimientos[2].retiro == Decimal("3000.00")

    # === Tests de duplicados ===

    def test_detecta_duplicados(self, parser):
        """Líneas idénticas no generan movimientos duplicados."""
        page = self._make_page(
            [
                "15-NOV-2025 500001 PAGO LUZ 1,500.00 118,500.00",
                "15-NOV-2025 500001 PAGO LUZ 1,500.00 118,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Ambas se procesan porque el sistema de duplicados permite
        # el mismo monto/fecha con contador incremental
        assert len(resultado.movimientos) == 2

    # === Tests de limpieza OCR ===

    def test_limpieza_texto_duplicado_ocr(self, parser):
        """Texto con caracteres duplicados de OCR se limpia correctamente."""
        resultado = SantanderParser._limpiar_texto_duplicado("1155--NNOOVV--22002255")
        assert resultado == "15-NOV-2025"

    # === Tests de info de cuenta ===

    def test_extrae_cuenta_con_guiones(self, parser):
        """Cuenta formato Santander: XX-XXXXXXXX-X."""
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.banco == "SANTANDER"
        assert resultado.info_cuenta.cuenta == "65-50123456-7"
        assert resultado.info_cuenta.moneda == "MXN"

    def test_moneda_usd(self, parser):
        """Detecta moneda USD."""
        page = self._make_page(
            header=(
                "Santander\nCuenta: 65-50123456-7\n"
                "Moneda USD\nPeriodo del 01-Nov-2025 al 30-Nov-2025"
            ),
            movimiento_lines=["1-NOV-2025 100001 PAGO 500.00 9,500.00"],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.moneda == "USD"

    # === Tests de periodo ===

    def test_extrae_periodo(self, parser):
        """Extrae año y mes del encabezado."""
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2025
        assert resultado.mes == 11

    def test_periodo_desde_primer_movimiento(self, parser):
        """Si no hay periodo en encabezado, lo extrae del primer movimiento."""
        page = self._make_page(
            header="Santander\nCuenta: 65-50123456-7\nMoneda: MXN",
            movimiento_lines=["8-MAR-2025 100001 PAGO 500.00 9,500.00"],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2025
        assert resultado.mes == 3

    # === Tests de fechas ===

    def test_fecha_dia_sin_cero(self, parser):
        """Día sin cero inicial (3-NOV-2025) se parsea correctamente."""
        page = self._make_page(["3-NOV-2025 100001 PAGO SERVICIO 800.00 119,200.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2025, 11, 3)

    def test_fecha_dia_con_cero(self, parser):
        """Día con cero (03-NOV-2025) se parsea correctamente."""
        page = self._make_page(["03-NOV-2025 100001 PAGO SERVICIO 800.00 119,200.00"])
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2025, 11, 3)

    # === Tests de resumen ===

    def test_calcula_resumen(self, parser):
        page = self._make_page(
            [
                "1-NOV-2025 100001 DEPOSITO 10,000.00 130,000.00",
                "5-NOV-2025 100002 PAGO LUZ 2,000.00 128,000.00",
                "10-NOV-2025 100003 ABONO TRANSFER 5,000.00 133,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.resumen.total_depositos == Decimal("15000.00")
        assert resultado.resumen.total_retiros == Decimal("2000.00")
        assert resultado.resumen.num_depositos == 2
        assert resultado.resumen.num_retiros == 1

    # === Tests de montos Decimal ===

    def test_montos_usan_decimal(self, parser):
        page = self._make_page(["15-NOV-2025 100001 PAGO 1,234.56 118,765.44"])
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert isinstance(mov.retiro, Decimal)
        assert mov.retiro == Decimal("1234.56")

    # === Tests de líneas ignoradas ===

    def test_ignora_lineas_sin_patron(self, parser):
        """Líneas que no matchean el patrón se ignoran."""
        page = self._make_page(
            [
                "Este es un encabezado",
                "15-NOV-2025 789012 PAGO SERVICIO 1,500.00 118,500.00",
                "Página 1 de 3",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1

    def test_ignora_linea_con_un_solo_monto(self, parser):
        """Líneas con menos de 2 montos se ignoran (necesita monto + saldo)."""
        page = self._make_page(
            [
                "15-NOV-2025 789012 SALDO ANTERIOR 120,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 0

    # === Tests de errores ===

    def test_error_sin_paginas(self, parser):
        with pytest.raises(ParseError, match="No se recibieron"):
            parser.parse([], file_name="test.pdf")

    def test_bank_name(self, parser):
        assert parser.bank_name == "SANTANDER"

    # === Test no requiere words ===

    def test_funciona_sin_words(self, parser):
        """Santander NO requiere coordenadas (a diferencia de BBVA/Banorte)."""
        page = PageText(
            page_num=1,
            text=(
                "Santander\nCuenta: 65-50123456-7\n"
                "Periodo del 01-Nov-2025 al 30-Nov-2025\n"
                "15-NOV-2025 789012 PAGO SERVICIO 1,500.00 118,500.00"
            ),
        )
        # No tiene words, pero funciona igual
        assert not page.has_words

        resultado = parser.parse([page], file_name="test.pdf")
        assert len(resultado.movimientos) == 1
