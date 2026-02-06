"""
Tests para el parser de Banorte.

Diferencias clave que estos tests validan vs BBVA:
- Fecha DD-MMM-YY (no DD/MMM).
- Clasificación por keywords cuando solo hay 2 montos.
- Clasificación por posición X cuando hay 3+ montos.
- Soporte de montos negativos con signo trailing (29,536.44-).
- Filtrado de SALDO ANTERIOR.
- Solo procesa páginas con "DETALLE DE MOVIMIENTOS".
"""

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.input.bank_parsers.banorte_parser import BanorteParser
from src.domain.exceptions import ParseError
from src.domain.models.page_text import PageText
from src.domain.models.word_info import WordInfo


class TestBanorteParser:
    """Tests unitarios para BanorteParser."""

    @pytest.fixture
    def parser(self):
        return BanorteParser()

    # === Helpers ===

    def _make_word(self, text: str, x0: float, top: float, x1: float | None = None) -> WordInfo:
        if x1 is None:
            x1 = x0 + len(text) * 7
        return WordInfo(text=text, x0=x0, x1=x1, top=top, bottom=top + 12)

    def _make_banorte_page(
        self,
        fecha: str = "05-OCT-24",
        concepto_words: list[str] | None = None,
        montos: list[tuple[str, float]] | None = None,
        include_header: bool = True,
        include_marker: bool = True,
        extra_lines: list[tuple[str, float]] | None = None,
    ) -> PageText:
        """Crea una página simulada de Banorte.

        Args:
            fecha: Fecha del movimiento (DD-MMM-YY).
            concepto_words: Palabras del concepto. Default: ["PAGO", "SERVICIO"].
            montos: Lista de (monto_str, x_pos). Default: un retiro + saldo.
            include_header: Si True, agrega encabezado con cuenta/periodo.
            include_marker: Si True, agrega "DETALLE DE MOVIMIENTOS".
            extra_lines: Líneas adicionales como (texto, top_y).
        """
        if concepto_words is None:
            concepto_words = ["PAGO", "SERVICIO"]
        if montos is None:
            montos = [("1,500.00", 460.0), ("120,000.00", 530.0)]

        words: list[WordInfo] = []
        text_parts: list[str] = []
        y_offset = 50.0

        if include_header:
            # Encabezado
            words.append(self._make_word("BANORTE", 50, y_offset))
            words.append(self._make_word("Banco", 120, y_offset))
            words.append(self._make_word("Mercantil", 165, y_offset))
            y_offset += 15

            words.append(self._make_word("CUENTA", 50, y_offset))
            words.append(self._make_word("PRODUCTIVA", 110, y_offset))
            words.append(self._make_word("ESPECIAL", 190, y_offset))
            words.append(self._make_word("0987654321", 260, y_offset))
            y_offset += 15

            words.append(self._make_word("Periodo", 50, y_offset))
            words.append(self._make_word("Del", 110, y_offset))
            words.append(self._make_word("01-OCT-24", 140, y_offset))
            words.append(self._make_word("Al", 220, y_offset))
            words.append(self._make_word("31-OCT-24", 240, y_offset))
            y_offset += 15

            text_parts.append("BANORTE Banco Mercantil")
            text_parts.append("CUENTA PRODUCTIVA ESPECIAL 0987654321")
            text_parts.append("Periodo Del 01-OCT-24 Al 31-OCT-24")

        if include_marker:
            words.append(self._make_word("DETALLE", 50, y_offset))
            words.append(self._make_word("DE", 110, y_offset))
            words.append(self._make_word("MOVIMIENTOS", 130, y_offset))
            y_offset += 20
            text_parts.append("DETALLE DE MOVIMIENTOS")

        # Línea de movimiento
        mov_y = y_offset
        words.append(self._make_word(fecha, 50, mov_y))

        concepto_x = 140.0
        for palabra in concepto_words:
            words.append(self._make_word(palabra, concepto_x, mov_y))
            concepto_x += len(palabra) * 7 + 5

        for monto_str, monto_x in montos:
            words.append(self._make_word(monto_str, monto_x, mov_y))

        mov_text = f"{fecha} {' '.join(concepto_words)} " + " ".join(m[0] for m in montos)
        text_parts.append(mov_text)

        # Líneas adicionales
        if extra_lines:
            for texto_extra, extra_y in extra_lines:
                for i, word in enumerate(texto_extra.split()):
                    words.append(self._make_word(word, 140 + i * 50, extra_y))
                text_parts.append(texto_extra)

        return PageText(
            page_num=1,
            text="\n".join(text_parts),
            words=words,
        )

    # === Tests de clasificación por keywords (2 montos) ===

    def test_retiro_por_keyword_default(self, parser):
        """Con 2 montos, si el concepto NO es keyword de depósito → retiro."""
        page = self._make_banorte_page(
            concepto_words=["PAGO", "SERVICIO"],
            montos=[("1,500.00", 400.0), ("118,500.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("1500.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

    def test_deposito_por_keyword_spei(self, parser):
        """Con 2 montos, 'SPEI RECIBIDO' → depósito."""
        page = self._make_banorte_page(
            concepto_words=["SPEI", "RECIBIDO", "EMPRESA", "SA"],
            montos=[("50,000.00", 400.0), ("170,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("50000.00")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_deposito_por_keyword_deposito(self, parser):
        """Con 2 montos, concepto que empieza con 'DEPOSITO' → depósito."""
        page = self._make_banorte_page(
            concepto_words=["DEPOSITO", "EN", "EFECTIVO"],
            montos=[("10,000.00", 400.0), ("130,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("10000.00")
        assert mov.tipo == "deposito"

    def test_deposito_por_keyword_interes(self, parser):
        """Con 2 montos, concepto que empieza con 'INTERES' → depósito."""
        page = self._make_banorte_page(
            concepto_words=["INTERES", "NETO"],
            montos=[("234.56", 400.0), ("120,234.56", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("234.56")

    # === Tests de clasificación por posición X (3+ montos) ===

    def test_deposito_por_posicion_x_3_montos(self, parser):
        """Con 3 montos, posición X en rango depósito (370-445) → depósito."""
        page = self._make_banorte_page(
            concepto_words=["ABONO", "VARIOS"],
            montos=[
                ("25,000.00", 400.0),  # x=400, rango depósito (370-445)
                ("0.00", 460.0),  # x=460, rango retiro (445-515) pero es 0
                ("145,000.00", 530.0),  # x=530, saldo (≥515, se ignora)
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("25000.00")

    def test_retiro_por_posicion_x_3_montos(self, parser):
        """Con 3 montos, posición X en rango retiro (445-515) → retiro."""
        page = self._make_banorte_page(
            concepto_words=["CHEQUE"],
            montos=[
                ("0.00", 400.0),  # x=400, depósito pero es 0
                ("5,000.00", 460.0),  # x=460, rango retiro (445-515)
                ("115,000.00", 530.0),  # x=530, saldo
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("5000.00")

    # === Tests de montos negativos ===

    def test_monto_negativo_trailing(self, parser):
        """Monto con signo menos al final (29,536.44-) debe procesarse."""
        page = self._make_banorte_page(
            concepto_words=["DEVOLUCION", "CARGO"],
            montos=[("29,536.44-", 400.0), ("149,536.44", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Con keyword DEVOLUCION no está en _DEPOSIT_KEYWORDS → retiro negativo
        # Pero el modelo Movimiento no permite negativos, así que se descarta
        assert len(resultado.movimientos) == 0

    # === Tests de filtrado ===

    def test_filtra_saldo_anterior(self, parser):
        """Líneas con 'SALDO ANTERIOR' no deben generar movimiento."""
        page = self._make_banorte_page(
            concepto_words=["SALDO", "ANTERIOR"],
            montos=[("120,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 0

    def test_ignora_paginas_sin_marcador(self, parser):
        """Páginas sin 'DETALLE DE MOVIMIENTOS' se ignoran."""
        page = self._make_banorte_page(
            include_marker=False,
            montos=[("1,500.00", 460.0), ("120,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 0

    # === Tests de info de cuenta ===

    def test_extrae_info_cuenta(self, parser):
        page = self._make_banorte_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.banco == "BANORTE"
        assert resultado.info_cuenta.cuenta == "0987654321"
        assert resultado.info_cuenta.moneda == "MXN"

    # === Tests de periodo ===

    def test_extrae_periodo_dd_mmm_yy(self, parser):
        """Extrae año y mes del formato 'Periodo Del DD-MMM-YY'."""
        page = self._make_banorte_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2024
        assert resultado.mes == 10

    def test_fecha_movimiento_formato_dd_mmm_yy(self, parser):
        """Fecha DD-MMM-YY se parsea correctamente."""
        page = self._make_banorte_page(
            fecha="15-OCT-24",
            montos=[("1,000.00", 460.0), ("119,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2024, 10, 15)

    # === Tests de referencia ===

    def test_extrae_referencia_formato_referencia(self, parser):
        """Extrae referencia con formato 'REFERENCIA: ABC123'."""
        page = self._make_banorte_page(
            concepto_words=["PAGO", "SERVICIO", "REFERENCIA:", "ABC123"],
            montos=[("500.00", 460.0), ("119,500.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].referencia == "ABC123"

    def test_extrae_referencia_formato_cve_rast(self, parser):
        """Extrae referencia con formato 'CVE RAST: XYZ789'."""
        page = self._make_banorte_page(
            concepto_words=["SPEI", "RECIBIDO", "CVE", "RAST:", "XYZ789"],
            montos=[("10,000.00", 400.0), ("130,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].referencia == "XYZ789"

    # === Tests de resumen ===

    def test_calcula_resumen(self, parser):
        page = self._make_banorte_page(
            montos=[("5,000.00", 460.0), ("115,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.resumen.total_retiros == Decimal("5000.00")
        assert resultado.resumen.num_retiros == 1

    # === Tests de montos Decimal ===

    def test_montos_usan_decimal(self, parser):
        page = self._make_banorte_page(
            montos=[("1,234.56", 460.0), ("118,765.44", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert isinstance(mov.retiro, Decimal)
        assert mov.retiro == Decimal("1234.56")

    # === Tests de errores ===

    def test_error_sin_paginas(self, parser):
        with pytest.raises(ParseError, match="No se recibieron"):
            parser.parse([], file_name="test.pdf")

    def test_error_sin_words(self, parser):
        page = PageText(page_num=1, text="BANORTE\nDETALLE DE MOVIMIENTOS")
        with pytest.raises(ParseError, match="palabras con coordenadas"):
            parser.parse([page], file_name="test.pdf")

    def test_bank_name(self, parser):
        assert parser.bank_name == "BANORTE"
