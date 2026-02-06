"""
Tests para el parser de BBVA.

Estos tests verifican la lógica de parseo usando PageText con palabras
simuladas (WordInfo). No necesitan un PDF real — eso es un test de
integración que iría en tests/integration/.

La idea: simular las palabras que pdfplumber extraería de un PDF de BBVA
y verificar que el parser las clasifica correctamente.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.input.bank_parsers.bbva_parser import BBVAParser
from src.domain.exceptions import ParseError
from src.domain.models.page_text import PageText
from src.domain.models.word_info import WordInfo


class TestBBVAParser:
    """Tests unitarios para BBVAParser."""

    @pytest.fixture
    def parser(self):
        return BBVAParser()

    # === Helpers para crear datos simulados ===

    def _make_word(self, text: str, x0: float, top: float, x1: float | None = None) -> WordInfo:
        """Crea un WordInfo con valores por defecto razonables."""
        if x1 is None:
            x1 = x0 + len(text) * 7  # ~7 pts por carácter
        return WordInfo(text=text, x0=x0, x1=x1, top=top, bottom=top + 12)

    def _make_page_with_movement(
        self,
        fecha: str = "05/OCT",
        concepto: str = "PAGO NOMINA",
        cargo_monto: str | None = None,
        abono_monto: str | None = None,
        cargo_x: float = 350.0,
        abono_x: float = 420.0,
        saldo_monto: str = "120,000.00",
        saldo_x: float = 490.0,
        encabezado: bool = True,
        año_texto: str = "Periodo: 01 OCT 2024 AL 31 OCT 2024",
    ) -> PageText:
        """Crea una página simulada con un movimiento de BBVA.

        Simula la estructura típica de un PDF de BBVA:
        - Línea de encabezado con info de cuenta y periodo.
        - Línea de movimiento con fecha, concepto, monto y saldo.

        Args:
            fecha: Fecha del movimiento (ej: "05/OCT").
            concepto: Texto del concepto.
            cargo_monto: Monto de cargo (None si no aplica).
            abono_monto: Monto de abono (None si no aplica).
            cargo_x: Posición X del cargo (debe ser < 400).
            abono_x: Posición X del abono (debe ser 400-470).
            saldo_monto: Monto del saldo.
            saldo_x: Posición X del saldo (debe ser >= 470).
            encabezado: Si True, agrega líneas de encabezado con cuenta/periodo.
            año_texto: Texto con el periodo para extraer año/mes.
        """
        words: list[WordInfo] = []
        y_offset = 50.0

        if encabezado:
            # Línea de encabezado: nombre del banco
            words.append(self._make_word("BBVA", 50, y_offset))
            words.append(self._make_word("BANCOMER,", 100, y_offset))
            words.append(self._make_word("S.A.", 170, y_offset))
            y_offset += 15

            # Línea de cuenta
            words.append(self._make_word("No.", 50, y_offset))
            words.append(self._make_word("Cuenta:", 80, y_offset))
            words.append(self._make_word("0123456789", 140, y_offset))
            y_offset += 15

            # Línea de periodo
            for i, word in enumerate(año_texto.split()):
                words.append(self._make_word(word, 50 + i * 50, y_offset))
            y_offset += 30

        # Línea de movimiento
        dia, mes = fecha.split("/")
        words.append(self._make_word(fecha, 50, y_offset))

        # Concepto (una o más palabras)
        concepto_x = 110.0
        for palabra in concepto.split():
            words.append(self._make_word(palabra, concepto_x, y_offset))
            concepto_x += len(palabra) * 7 + 5

        # Monto de cargo (columna izquierda, x < 400)
        if cargo_monto:
            words.append(self._make_word(cargo_monto, cargo_x, y_offset))

        # Monto de abono (columna media, 400 <= x < 470)
        if abono_monto:
            words.append(self._make_word(abono_monto, abono_x, y_offset))

        # Saldo (columna derecha, x >= 470)
        words.append(self._make_word(saldo_monto, saldo_x, y_offset))

        # Construir texto plano a partir de las palabras
        text_parts = [año_texto] if encabezado else []
        text_parts.append("BBVA BANCOMER, S.A.\nNo. Cuenta: 0123456789" if encabezado else "")
        text_parts.append(
            f"{fecha} {concepto} " f"{cargo_monto or ''} {abono_monto or ''} {saldo_monto}"
        )

        return PageText(
            page_num=1,
            text="\n".join(text_parts),
            words=words,
        )

    # === Tests de parseo ===

    def test_parsea_cargo_por_posicion_x(self, parser):
        """Un monto con x < 400 debe clasificarse como cargo (retiro)."""
        page = self._make_page_with_movement(
            fecha="05/OCT",
            concepto="PAGO LUZ",
            cargo_monto="1,500.00",
            cargo_x=350.0,  # x < 400 → cargo
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("1500.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

    def test_parsea_abono_por_posicion_x(self, parser):
        """Un monto con 400 <= x < 470 debe clasificarse como abono (depósito)."""
        page = self._make_page_with_movement(
            fecha="10/OCT",
            concepto="TRANSFERENCIA",
            abono_monto="50,000.00",
            abono_x=420.0,  # 400 <= x < 470 → abono
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("50000.00")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_ignora_saldo(self, parser):
        """Un monto con x >= 470 es saldo y NO debe crear movimiento si
        no hay cargo ni abono."""
        # Solo saldo, sin cargo ni abono
        words = [
            self._make_word("BBVA", 50, 50),
            self._make_word("No.", 50, 65),
            self._make_word("Cuenta:", 80, 65),
            self._make_word("0123456789", 140, 65),
            self._make_word("Periodo:", 50, 80),
            self._make_word("01", 110, 80),
            self._make_word("OCT", 130, 80),
            self._make_word("2024", 160, 80),
            self._make_word("AL", 200, 80),
            self._make_word("31", 220, 80),
            self._make_word("OCT", 240, 80),
            self._make_word("2024", 270, 80),
            # Movimiento con solo saldo (x=490, >= 470)
            self._make_word("05/OCT", 50, 120),
            self._make_word("SALDO", 110, 120),
            self._make_word("INICIAL", 160, 120),
            self._make_word("120,000.00", 490, 120),  # x >= 470 → saldo
        ]
        page = PageText(
            page_num=1,
            text=(
                "BBVA\nNo. Cuenta: 0123456789\n"
                "Periodo: 01 OCT 2024 AL 31 OCT 2024\n"
                "05/OCT SALDO INICIAL 120,000.00"
            ),
            words=words,
        )
        resultado = parser.parse([page], file_name="test.pdf")
        # No debería haber movimientos porque solo había saldo
        assert len(resultado.movimientos) == 0

    def test_extrae_info_cuenta(self, parser):
        """Debe extraer banco='BBVA', cuenta del encabezado, moneda='MXN'."""
        page = self._make_page_with_movement(
            cargo_monto="100.00",
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.banco == "BBVA"
        assert resultado.info_cuenta.cuenta == "0123456789"
        assert resultado.info_cuenta.moneda == "MXN"

    def test_extrae_año_del_periodo(self, parser):
        """El año debe extraerse del texto del periodo, no hardcodeado."""
        page = self._make_page_with_movement(
            cargo_monto="100.00",
            año_texto="Periodo: 01 OCT 2024 AL 31 OCT 2024",
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2024
        assert resultado.mes == 10

    def test_fecha_movimiento_usa_año_extraido(self, parser):
        """La fecha del movimiento debe usar el año extraído del periodo."""
        page = self._make_page_with_movement(
            fecha="15/OCT",
            cargo_monto="200.00",
            año_texto="Periodo: 01 OCT 2024 AL 31 OCT 2024",
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2024, 10, 15)

    def test_montos_usan_decimal(self, parser):
        """Los montos deben ser Decimal, no float (precisión monetaria)."""
        page = self._make_page_with_movement(
            cargo_monto="1,234.56",
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert isinstance(mov.retiro, Decimal)
        assert mov.retiro == Decimal("1234.56")

    def test_calcula_resumen(self, parser):
        """Debe calcular totales correctamente."""
        page = self._make_page_with_movement(
            cargo_monto="5,000.00",
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.resumen.total_retiros == Decimal("5000.00")
        assert resultado.resumen.num_retiros == 1
        assert resultado.resumen.total_depositos == Decimal("0")
        assert resultado.resumen.num_depositos == 0

    def test_error_sin_paginas(self, parser):
        """Debe lanzar ParseError si no recibe páginas."""
        with pytest.raises(ParseError, match="No se recibieron"):
            parser.parse([], file_name="test.pdf")

    def test_error_sin_words(self, parser):
        """Debe lanzar ParseError si las páginas no tienen words."""
        page = PageText(
            page_num=1,
            text="BBVA\nNo. Cuenta: 0123456789\nPeriodo: 01 OCT 2024",
            words=[],  # Sin palabras con coordenadas
        )
        with pytest.raises(ParseError, match="palabras con coordenadas"):
            parser.parse([page], file_name="test.pdf")

    def test_bank_name(self, parser):
        """El nombre del banco debe ser 'BBVA'."""
        assert parser.bank_name == "BBVA"


class TestKeywordBankIdentifier:
    """Tests para el identificador de bancos por keywords."""

    @pytest.fixture
    def identifier(self):
        from src.adapters.input.bank_identifiers.keyword_identifier import (
            KeywordBankIdentifier,
        )

        return KeywordBankIdentifier()

    @pytest.mark.parametrize(
        "texto, banco_esperado",
        [
            ("BBVA BANCOMER, S.A. Institución de Banca Múltiple", "BBVA"),
            ("BBVA México S.A.", "BBVA"),
            ("Banco Mercantil del Norte S.A. BANORTE", "BANORTE"),
            ("CITIBANAMEX Estado de cuenta", "CITIBANAMEX"),
            ("Banco Nacional de México", "CITIBANAMEX"),
            ("SCOTIABANK Inverlat S.A.", "SCOTIABANK"),
            ("Banco Monex S.A.", "MONEX"),
            ("BANK OF AMERICA NA", "BANK_OF_AMERICA"),
            ("J.P. MORGAN CHASE", "JP_MORGAN"),
            ("Banco Santander México", "SANTANDER"),
        ],
    )
    def test_identifica_bancos(self, identifier, texto, banco_esperado):
        assert identifier.identify(texto) == banco_esperado

    def test_case_insensitive(self, identifier):
        assert identifier.identify("bbva bancomer") == "BBVA"
        assert identifier.identify("BBVA BANCOMER") == "BBVA"
        assert identifier.identify("Bbva Bancomer") == "BBVA"

    def test_banco_no_reconocido(self, identifier):
        assert identifier.identify("Texto sin banco reconocible") is None

    def test_texto_vacio(self, identifier):
        assert identifier.identify("") is None

    def test_citibanamex_antes_que_citi(self, identifier):
        """CITIBANAMEX debe identificarse como CITIBANAMEX, no como CITI."""
        assert identifier.identify("CITIBANAMEX") == "CITIBANAMEX"

    def test_citi_sin_banamex(self, identifier):
        """CITIBANK (sin BANAMEX) debe identificarse como CITI."""
        assert identifier.identify("CITIBANK NA USA") == "CITI"