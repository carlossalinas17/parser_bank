"""
Tests para el parser de HSBC.

Diferencias clave que estos tests validan:
- Decodificación EBCDIC (CID encoding → texto legible).
- Columnas detectadas dinámicamente desde el header.
- Clasificación retiro/depósito por posición X (coordenadas).
- Fecha solo con día (DD), mes/año del periodo.
- Referencias multi-línea (ej: "13651011" + "41234").
- Moneda MXN por default.
- Cuenta 10 dígitos.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.input.bank_parsers.hsbc_ebcdic import decode_hsbc_text, needs_ebcdic_decoding
from src.adapters.input.bank_parsers.hsbc_parser import HsbcParser
from src.domain.exceptions import ParseError
from src.domain.models.page_text import PageText
from src.domain.models.word_info import WordInfo


class TestHsbcEbcdicDecoder:
    """Tests del decodificador EBCDIC para HSBC."""

    def test_decode_uppercase(self):
        """CUENTA INTEGRAL se decodifica correctamente."""
        encoded = (
            "\u02c6(cid:228)\u00af(cid:213)\u00aa`@"
            "(cid:201)(cid:213)\u00aa\u00af\u02d9(cid:217)`(cid:211)"
        )
        assert decode_hsbc_text(encoded) == "CUENTA INTEGRAL"

    def test_decode_lowercase(self):
        """'Estado de Cuenta' se decodifica."""
        # E s t a d o   d e   C u e n t a
        encoded = (
            "\u00af\u00a2\u00a3(cid:129)(cid:132)(cid:150)@"
            "(cid:132)(cid:133)@"
            "\u02c6\u2044(cid:133)(cid:149)\u00a3(cid:129)"
        )
        assert decode_hsbc_text(encoded) == "Estado de Cuenta"

    def test_decode_digits(self):
        """Número de cuenta 4007185804 se decodifica."""
        encoded = "(cid:244)(cid:240)(cid:240)(cid:247)\u00e6\u0142\u0131\u0142(cid:240)(cid:244)"
        assert decode_hsbc_text(encoded) == "4007185804"

    def test_decode_amount(self):
        """Monto $1,309.00 se decodifica."""
        encoded = "[\u00e6k(cid:243)(cid:240)\u00f8K(cid:240)(cid:240)"
        assert decode_hsbc_text(encoded) == "$1,309.00"

    def test_decode_date(self):
        """Fecha 01/11/2025 se decodifica."""
        encoded = "(cid:240)\u00e6a\u00e6\u00e6a(cid:242)(cid:240)(cid:242)\u0131"
        assert decode_hsbc_text(encoded) == "01/11/2025"

    def test_decode_preserves_newlines(self):
        decoded = decode_hsbc_text("(cid:129)\n(cid:130)")
        assert decoded == "a\nb"

    def test_decode_unknown_cid(self):
        """CID desconocidos se preservan con brackets."""
        decoded = decode_hsbc_text("(cid:999)")
        assert "(cid:999)" in decoded


class TestHsbcParser:
    """Tests unitarios para HsbcParser."""

    @pytest.fixture
    def parser(self):
        return HsbcParser()

    # === Helpers ===

    def _word(self, text: str, x0: float, x1: float, y: float) -> WordInfo:
        return WordInfo(text=text, x0=x0, x1=x1, top=y, bottom=y + 10)

    def _make_hsbc_page(
        self,
        movements: list[dict] | None = None,
        header_y: float = 100.0,
        include_header: bool = True,
        include_marker: bool = True,
        marker_text: str = "DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804",
        period_text: str = "01/11/2025 al 30/11/2025",
        cuenta_text: str = "CUENTA INTEGRAL No.  4007185804",
    ) -> PageText:
        """Crea una página simulada de HSBC con words ya decodificadas.

        Los movements son dicts con keys: day, desc, ref, retiro, deposito, saldo.
        Las coordenadas X se asignan según las columnas estándar HSBC:
          Día=43, Desc=62, Ref=302, Retiro=370, Deposito=435, Saldo=510
        """
        words: list[WordInfo] = []
        text_parts: list[str] = []

        # Encabezado general
        text_parts.append("CUENTA INTEGRAL")
        text_parts.append("Estado de Cuenta")
        text_parts.append(f"Periodo del {period_text}")
        text_parts.append("PESOS MEXICANOS")
        text_parts.append(cuenta_text)

        # Marcador de tabla
        if include_marker:
            words.append(self._word(marker_text, 41, 280, header_y - 15))
            text_parts.append(marker_text)

        # Header de columnas
        if include_header:
            words.append(self._word("DUa", 43, 55, header_y))
            words.append(self._word("Descripcion", 142, 190, header_y))
            words.append(self._word("Referencia/", 282, 325, header_y))
            words.append(self._word("Retiro/Cargo", 350, 400, header_y))
            words.append(self._word("Deposito/Abono", 422, 485, header_y))
            words.append(self._word("Saldo", 529, 550, header_y))
            words.append(self._word("Serial", 292, 315, header_y + 5))
            text_parts.append("DUa Descripcion Referencia/ Retiro/Cargo Deposito/Abono Saldo")

        # Movimientos
        if movements:
            y = header_y + 20
            for mov in movements:
                day = mov.get("day", "")
                desc = mov.get("desc", "")
                ref = mov.get("ref", "")
                retiro = mov.get("retiro", "")
                deposito = mov.get("deposito", "")
                saldo = mov.get("saldo", "")

                if day:
                    words.append(self._word(str(day), 43, 53, y))
                if desc:
                    words.append(self._word(desc, 62, 240, y))
                if ref:
                    words.append(self._word(ref, 302, 336, y))
                if retiro:
                    words.append(self._word(retiro, 370, 403, y))
                if deposito:
                    words.append(self._word(deposito, 435, 473, y))
                if saldo:
                    words.append(self._word(saldo, 510, 565, y))

                line = f"{day} {desc} {ref} {retiro} {deposito} {saldo}".strip()
                text_parts.append(line)
                y += 18

        text = "\n".join(text_parts)
        return PageText(page_num=1, text=text, words=words)

    # === Tests de depósitos (columna Depósito/Abono) ===

    def test_deposito_por_columna_x(self, parser):
        """Monto en columna Depósito/Abono → depósito."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "03",
                    "desc": "TRANSFERENCIA BPI DESDE LA CUENTA 9798",
                    "ref": "13651011",
                    "deposito": "$ 40,000.00",
                    "saldo": "$ 11,687,976.35",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("40000.00")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_multiples_depositos(self, parser):
        """Varios depósitos en la misma página."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "03",
                    "desc": "TRANSFERENCIA BPI",
                    "ref": "111",
                    "deposito": "$ 40,000.00",
                    "saldo": "$ 100,000.00",
                },
                {
                    "day": "05",
                    "desc": "TRANSFERENCIA BPI",
                    "ref": "222",
                    "deposito": "$ 50,000.00",
                    "saldo": "$ 150,000.00",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        assert resultado.movimientos[0].deposito == Decimal("40000.00")
        assert resultado.movimientos[1].deposito == Decimal("50000.00")

    # === Tests de retiros (columna Retiro/Cargo) ===

    def test_retiro_por_columna_x(self, parser):
        """Monto en columna Retiro/Cargo → retiro."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "14",
                    "desc": "COMISION X SERVICIO GBS",
                    "ref": "16922999",
                    "retiro": "$ 1,309.00",
                    "saldo": "$ 12,188,048.49",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("1309.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

    def test_retiro_iva(self, parser):
        """I.V.A. aparece como retiro."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "14",
                    "desc": "I.V.A.",
                    "ref": "11140000",
                    "retiro": "$ 209.44",
                    "saldo": "$ 12,187,839.05",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].retiro == Decimal("209.44")

    def test_retiro_isr(self, parser):
        """I.S.R. RETENIDO aparece como retiro."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "28",
                    "desc": "I.S.R. RETENIDO",
                    "ref": "11280001",
                    "retiro": "$ 5,019.07",
                    "saldo": "$ 12,858,591.80",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].retiro == Decimal("5019.07")

    # === Tests mixtos (retiros y depósitos en la misma página) ===

    def test_retiro_y_deposito_misma_pagina(self, parser):
        """Retiros y depósitos se clasifican correctamente por columna X."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "14",
                    "desc": "TRANSFERENCIA BPI",
                    "ref": "111",
                    "deposito": "$ 55,000.00",
                    "saldo": "$ 12,000,000.00",
                },
                {
                    "day": "14",
                    "desc": "COMISION",
                    "ref": "222",
                    "retiro": "$ 1,309.00",
                    "saldo": "$ 11,998,691.00",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        assert resultado.movimientos[0].tipo == "deposito"
        assert resultado.movimientos[1].tipo == "retiro"

    # === Tests de fecha (solo día DD) ===

    def test_fecha_dia_simple(self, parser):
        """Día 03 con periodo noviembre 2025 → 2025-11-03."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "03",
                    "desc": "TEST",
                    "ref": "111",
                    "deposito": "$ 100.00",
                    "saldo": "$ 100.00",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2025, 11, 3)

    def test_fecha_dia_sin_cero(self, parser):
        """Día 7 → 2025-11-07."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "7",
                    "desc": "TEST",
                    "ref": "111",
                    "deposito": "$ 100.00",
                    "saldo": "$ 100.00",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2025, 11, 7)

    # === Tests de info de cuenta ===

    def test_extrae_cuenta_10_digitos(self, parser):
        page = self._make_hsbc_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.banco == "HSBC"
        assert resultado.info_cuenta.cuenta == "4007185804"

    def test_moneda_default_mxn(self, parser):
        page = self._make_hsbc_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.moneda == "MXN"

    def test_moneda_usd_si_detectada(self, parser):
        page = self._make_hsbc_page()
        # Override text to include USD
        usd_text = page.text.replace("PESOS MEXICANOS", "USD DOLARES AMERICANOS")
        page_usd = PageText(page_num=1, text=usd_text, words=page.words)
        resultado = parser.parse([page_usd], file_name="test.pdf")

        assert resultado.info_cuenta.moneda == "USD"

    # === Tests de periodo ===

    def test_extrae_año_y_mes(self, parser):
        page = self._make_hsbc_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2025
        assert resultado.mes == 11

    def test_periodo_diciembre(self, parser):
        page = self._make_hsbc_page(period_text="01/12/2024 al 31/12/2024")
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2024
        assert resultado.mes == 12

    # === Tests de referencia multi-línea ===

    def test_referencia_multilinea(self, parser):
        """Referencia en dos líneas: '13651011' + '41234'."""
        words: list[WordInfo] = []
        y_marker = 85.0
        y_header = 100.0
        y_data = 120.0

        # Marker
        words.append(
            self._word("DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804", 41, 280, y_marker)
        )
        # Header
        words.append(self._word("DUa", 43, 55, y_header))
        words.append(self._word("Retiro/Cargo", 350, 400, y_header))
        words.append(self._word("Deposito/Abono", 422, 485, y_header))
        words.append(self._word("Saldo", 529, 550, y_header))
        # Movement line 1
        words.append(self._word("03", 43, 53, y_data))
        words.append(self._word("TRANSFERENCIA BPI DESDE LA CUENTA 9798", 62, 240, y_data))
        words.append(self._word("13651011", 302, 336, y_data))
        words.append(self._word("$ 40,000.00", 435, 473, y_data))
        words.append(self._word("$ 11,687,976.35", 510, 565, y_data))
        # Continuation line with ref
        words.append(self._word("41234", 313, 336, y_data + 10))

        text = (
            "CUENTA INTEGRAL\nEstado de Cuenta\n"
            "Periodo del 01/11/2025 al 30/11/2025\nPESOS MEXICANOS\n"
            "CUENTA INTEGRAL No.  4007185804\n"
            "DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804\n"
            "DUa Descripcion Retiro/Cargo Deposito/Abono Saldo\n"
            "03 TRANSFERENCIA BPI DESDE LA CUENTA 9798 13651011 $ 40,000.00 $ 11,687,976.35\n"
            "41234\n"
        )
        page = PageText(page_num=1, text=text, words=words)
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        assert "13651011" in resultado.movimientos[0].referencia
        assert "41234" in resultado.movimientos[0].referencia

    # === Tests de detección de tabla ===

    def test_pagina_sin_tabla_ignorada(self, parser):
        """Páginas sin 'DETALLE MOVIMIENTOS' no generan movimientos."""
        page = self._make_hsbc_page(include_marker=False)
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 0

    def test_pagina_sin_header_ignorada(self, parser):
        """Si no se detecta el header, no se parsean movimientos."""
        page = self._make_hsbc_page(
            include_header=False,
            movements=[
                {"day": "03", "desc": "TEST", "deposito": "$ 100.00"},
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 0

    # === Tests de resumen ===

    def test_calcula_resumen(self, parser):
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "03",
                    "desc": "DEP1",
                    "ref": "1",
                    "deposito": "$ 10,000.00",
                    "saldo": "$ 10,000.00",
                },
                {
                    "day": "05",
                    "desc": "DEP2",
                    "ref": "2",
                    "deposito": "$ 5,000.00",
                    "saldo": "$ 15,000.00",
                },
                {
                    "day": "14",
                    "desc": "COMISION",
                    "ref": "3",
                    "retiro": "$ 200.00",
                    "saldo": "$ 14,800.00",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.resumen.total_depositos == Decimal("15000.00")
        assert resultado.resumen.total_retiros == Decimal("200.00")
        assert resultado.resumen.num_depositos == 2
        assert resultado.resumen.num_retiros == 1

    # === Tests de Decimal ===

    def test_montos_usan_decimal(self, parser):
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "03",
                    "desc": "TEST",
                    "ref": "1",
                    "deposito": "$ 100.50",
                    "saldo": "$ 100.50",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert isinstance(resultado.movimientos[0].deposito, Decimal)

    # === Tests de errores ===

    def test_error_sin_paginas(self, parser):
        with pytest.raises(ParseError, match="No se recibieron"):
            parser.parse([], file_name="test.pdf")

    def test_error_sin_words(self, parser):
        """Si no hay words (coordenadas), lanza error descriptivo."""
        page = PageText(
            page_num=1,
            text="DETALLE MOVIMIENTOS CUENTA INTEGRAL No. 4007185804\nDUa Saldo\n"
            "Periodo del 01/11/2025 al 30/11/2025\nPESOS MEXICANOS\n"
            "CUENTA INTEGRAL No.  4007185804",
        )
        with pytest.raises(ParseError, match="words con coordenadas"):
            parser.parse([page], file_name="test.pdf")

    # === Tests generales ===

    def test_bank_name(self, parser):
        assert parser.bank_name == "HSBC"

    def test_ignora_lineas_sin_dia(self, parser):
        """Líneas sin día válido se ignoran como movimientos nuevos."""
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "03",
                    "desc": "TEST",
                    "ref": "111",
                    "deposito": "$ 100.00",
                    "saldo": "$ 100.00",
                },
                {"day": "", "desc": "Extra info", "ref": ""},
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1

    def test_concepto_extraido(self, parser):
        page = self._make_hsbc_page(
            movements=[
                {
                    "day": "14",
                    "desc": "COMISION X SERVICIO GBS",
                    "ref": "16922999",
                    "retiro": "$ 1,309.00",
                    "saldo": "$ 12,000.00",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].concepto == "COMISION X SERVICIO GBS"

    def test_tabla_termina_en_marker(self, parser):
        """Movimientos después de 'CoDi' se ignoran."""
        words: list[WordInfo] = []
        y_m = 85.0
        y_h = 100.0

        words.append(
            self._word("DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804", 41, 280, y_m)
        )
        words.append(self._word("DUa", 43, 55, y_h))
        words.append(self._word("Retiro/Cargo", 350, 400, y_h))
        words.append(self._word("Deposito/Abono", 422, 485, y_h))
        words.append(self._word("Saldo", 529, 550, y_h))
        # One valid movement
        words.append(self._word("03", 43, 53, 120))
        words.append(self._word("TEST", 62, 100, 120))
        words.append(self._word("$ 100.00", 435, 473, 120))
        words.append(self._word("$ 100.00", 510, 565, 120))
        # CoDi marker
        words.append(self._word("CoDi: Operacion procesada", 43, 300, 140))
        # Movement after marker (should be ignored)
        words.append(self._word("05", 43, 53, 160))
        words.append(self._word("SHOULD NOT APPEAR", 62, 200, 160))
        words.append(self._word("$ 999.00", 435, 473, 160))

        text = (
            "CUENTA INTEGRAL\nEstado de Cuenta\n"
            "Periodo del 01/11/2025 al 30/11/2025\nPESOS MEXICANOS\n"
            "CUENTA INTEGRAL No.  4007185804\n"
            "DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804\n"
            "DUa Retiro/Cargo Deposito/Abono Saldo\n"
            "03 TEST $ 100.00 $ 100.00\n"
            "CoDi: Operacion procesada\n"
            "05 SHOULD NOT APPEAR $ 999.00\n"
        )
        page = PageText(page_num=1, text=text, words=words)
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        assert resultado.movimientos[0].concepto == "TEST"


class TestHsbcConditionalDecoding:
    """Tests que verifican que la decodificación EBCDIC es condicional.

    La decodificación SOLO se aplica cuando el texto contiene tokens
    CID '(cid:NNN)'. Si el texto ya está limpio (como en tests unitarios
    o si un futuro PDF no usa encoding EBCDIC), se pasa sin modificar.

    ¿Por qué es crítico? Porque el mapeo EBCDIC convierte caracteres
    normales a símbolos: 'a' → '/', 'l' → '%', 'K' → '.', etc.
    Aplicarlo a texto limpio lo corrompe irremediablemente.
    """

    @pytest.fixture
    def parser(self):
        return HsbcParser()

    def _word(self, text: str, x0: float, x1: float, y: float) -> WordInfo:
        return WordInfo(text=text, x0=x0, x1=x1, top=y, bottom=y + 10)

    def test_needs_ebcdic_detects_cid_tokens(self):
        """Texto con tokens (cid:NNN) necesita decodificación."""
        assert needs_ebcdic_decoding("(cid:228)¯(cid:213)") is True

    def test_needs_ebcdic_clean_text(self):
        """Texto limpio NO necesita decodificación."""
        assert needs_ebcdic_decoding("CUENTA INTEGRAL") is False

    def test_needs_ebcdic_empty(self):
        """Texto vacío no necesita decodificación."""
        assert needs_ebcdic_decoding("") is False

    def test_texto_limpio_no_se_corrompe(self, parser):
        """Texto ya decodificado pasa sin modificación por el parser.

        Verifica que 'al' no se convierte en '/%' y que las fechas
        DD/MM/YYYY se preservan intactas.
        """
        page = PageText(
            page_num=1,
            text=(
                "CUENTA INTEGRAL\nEstado de Cuenta\n"
                "Periodo del 01/11/2025 al 30/11/2025\n"
                "PESOS MEXICANOS\n"
                "CUENTA INTEGRAL No.  4007185804\n"
                "DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804\n"
                "DUa Descripcion Retiro/Cargo Deposito/Abono Saldo\n"
                "03 TEST 111 $ 100.00 $ 100.00\n"
            ),
            words=[
                self._word("DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804", 41, 280, 85),
                self._word("DUa", 43, 55, 100),
                self._word("Retiro/Cargo", 350, 400, 100),
                self._word("Deposito/Abono", 422, 485, 100),
                self._word("Saldo", 529, 550, 100),
                self._word("03", 43, 53, 120),
                self._word("TEST", 62, 100, 120),
                self._word("111", 302, 320, 120),
                self._word("$ 100.00", 435, 473, 120),
                self._word("$ 100.00", 510, 565, 120),
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Si la decodificación se aplicara incorrectamente, no encontraría
        # el periodo porque "al" se convertiría en "/%"
        assert resultado.año == 2025
        assert resultado.mes == 11
        assert len(resultado.movimientos) == 1

    def test_texto_ebcdic_se_decodifica(self, parser):
        """Texto con encoding EBCDIC se decodifica correctamente.

        Verifica que cuando una página contiene tokens CID, la
        decodificación se aplica y el parser puede extraer el periodo.
        Usamos texto EBCDIC real para el periodo y texto limpio para
        el resto (ya que lo que importa es que la decodificación se active).
        """
        # Texto EBCDIC para "Periodo del 01/11/2025 al 30/11/2025"
        # Solo incluimos un token (cid:) para activar la decodificación
        ebcdic_periodo = (
            "(cid:215)\u00af(cid:153)\u00a8(cid:150)(cid:132)(cid:150)@"
            "(cid:132)\u00af(cid:147)@"
            "(cid:240)\u00e6a\u00e6\u00e6a(cid:242)(cid:240)(cid:242)\u0131@"
            "(cid:129)(cid:147)@"
            "(cid:243)(cid:240)a\u00e6\u00e6a(cid:242)(cid:240)(cid:242)\u0131"
        )

        page = PageText(
            page_num=1,
            text=(
                "\u02c6(cid:228)\u00af(cid:213)\u00aa`@(cid:201)(cid:213)\u00aa\u00af\u02d9(cid:217)`(cid:211)\n"
                f"{ebcdic_periodo}\n"
                "(cid:215)\u00af(cid:226)(cid:214)(cid:226)@(cid:212)\u00af\u02d9(cid:201)\u02c6`(cid:213)(cid:214)(cid:226)\n"
                "\u02c6(cid:228)\u00af(cid:213)\u00aa`@(cid:201)(cid:213)\u00aa\u00af\u02d9(cid:217)`(cid:211)@(cid:213)(cid:150)K@@(cid:244)(cid:240)(cid:240)(cid:247)\u00e6\u0142\u0131\u0142(cid:240)(cid:244)\n"
            ),
            words=[
                # Al menos 1 word con CID para activar decodificación
                self._word("(cid:226)(cid:129)(cid:147)(cid:132)(cid:150)", 529, 550, 100),
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Verifica que la decodificación funcionó: extrajo el periodo
        assert resultado.año == 2025
        assert resultado.mes == 11
        # Verifica que la cuenta se extrajo del texto EBCDIC
        assert resultado.info_cuenta.cuenta == "4007185804"

    def test_pagina_mixta_ebcdic_y_limpia(self, parser):
        """Si una página tiene tokens CID, TODA la página se decodifica.

        Esto es importante porque dentro del mismo PDF, algunas words
        pueden no tener tokens CID (ej: 'æł' = '18' en EBCDIC) pero
        siguen necesitando decodificación porque el encoding es del font.
        """
        # Página que tiene un token CID en el texto Y en una word
        page = PageText(
            page_num=1,
            text=(
                "\u02c6(cid:228)\u00af(cid:213)\u00aa`@(cid:201)(cid:213)\u00aa\u00af\u02d9(cid:217)`(cid:211)\n"
                "(cid:215)\u00af(cid:153)(cid:201)(cid:150)(cid:132)(cid:150)@(cid:132)\u00af(cid:147)@(cid:240)\u00e6a\u00e6\u00e6a(cid:242)(cid:240)(cid:242)\u0131@(cid:129)(cid:147)@(cid:243)(cid:240)a\u00e6\u00e6a(cid:242)(cid:240)(cid:242)\u0131\n"
                "(cid:215)\u00af(cid:226)(cid:214)(cid:226)@(cid:212)\u00af\u02d9(cid:201)\u02c6`(cid:213)(cid:214)(cid:226)\n"
                "\u02c6(cid:228)\u00af(cid:213)\u00aa`@(cid:201)(cid:213)\u00aa\u00af\u02d9(cid:217)`(cid:211)@(cid:213)(cid:150)K@@(cid:244)(cid:240)(cid:240)(cid:247)\u00e6\u0142\u0131\u0142(cid:240)(cid:244)\n"
            ),
            words=[
                # Word con CID token
                self._word("(cid:226)(cid:129)(cid:147)(cid:132)(cid:150)", 529, 550, 100),
                # Word sin CID pero que aún necesita decodificación (æł = 18)
                self._word("\u00e6\u0142", 43, 53, 120),
            ],
        )

        # Verificar la decodificación directamente con _decode_page
        # (no necesitamos parse() porque este test valida la decodificación,
        # no la extracción de movimientos)

        # La segunda word "æł" debería haberse decodificado a "18"
        # porque la página tiene CID tokens (en el texto y en word 1)
        decoded_page = parser._decode_page(page)
        decoded_words_text = [w.text for w in decoded_page.words]
        assert (
            "Saldo" in decoded_words_text
        )  # "(cid:226)(cid:129)(cid:147)(cid:132)(cid:150)" → "Saldo"
        assert "18" in decoded_words_text  # "æł" → "18"


class TestHsbcRealPdfPatterns:
    """Tests basados en patrones reales del PDF de HSBC noviembre 2025.

    Estos tests verifican escenarios específicos observados en el PDF
    real: movimientos que son solo depósitos, retiros por comisión,
    IVA e ISR como retiros, pago de intereses como depósito, y la
    estructura multi-página donde la tabla continúa.
    """

    @pytest.fixture
    def parser(self):
        return HsbcParser()

    def _word(self, text: str, x0: float, x1: float, y: float) -> WordInfo:
        return WordInfo(text=text, x0=x0, x1=x1, top=y, bottom=y + 10)

    def _make_page_with_real_coords(
        self,
        movements: list[dict],
        period_text: str = "01/11/2025 al 30/11/2025",
        header_y: float = 486.0,
        start_y: float = 500.0,
    ) -> PageText:
        """Crea una página usando coordenadas X reales del PDF HSBC.

        Coordenadas reales extraídas del PDF:
        - Día:        x0=43.20  x1=53.04
        - Descripción: x0=61.20  x1=240.24
        - Referencia:  x0=300.40 x1=336.16
        - Retiro:      x0=366.00 x1=402.72
        - Depósito:    x0=431.00 x1=473.24
        - Saldo:       x0=506.40 x1=565.92
        """
        words: list[WordInfo] = []
        text_parts: list[str] = [
            "CUENTA INTEGRAL",
            "Estado de Cuenta",
            f"Periodo del {period_text}",
            "PESOS MEXICANOS",
            "CUENTA INTEGRAL No.  4007185804",
        ]

        # Marker (real y: 471.10)
        words.append(
            self._word(
                "DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804", 41.20, 281.20, header_y - 15
            )
        )
        text_parts.append("DETALLE MOVIMIENTOS CUENTA INTEGRAL No.  4007185804")

        # Header (real y: 486.20)
        words.append(self._word("DUa", 41.50, 53.50, header_y))
        words.append(self._word("Descripción", 140.80, 185.44, header_y))
        words.append(self._word("Referencia/", 281.00, 323.24, header_y - 6))
        words.append(self._word("Retiro/Cargo", 349.20, 396.96, header_y))
        words.append(self._word("Depósito/Abono", 421.20, 481.44, header_y))
        words.append(self._word("Saldo", 527.70, 549.06, header_y))
        words.append(self._word("Serial", 291.30, 312.66, header_y + 4))

        y = start_y
        for mov in movements:
            day = mov.get("day", "")
            desc = mov.get("desc", "")
            ref = mov.get("ref", "")
            retiro = mov.get("retiro", "")
            deposito = mov.get("deposito", "")
            saldo = mov.get("saldo", "")
            ref2 = mov.get("ref2", "")  # Continuation ref line

            if day:
                words.append(self._word(str(day), 43.20, 53.04, y))
            if desc:
                words.append(self._word(desc, 61.20, 240.24, y))
            if ref:
                words.append(self._word(ref, 300.40, 336.16, y))
            if retiro:
                words.append(self._word(retiro, 366.00, 402.72, y))
            if deposito:
                words.append(self._word(deposito, 431.00, 473.24, y))
            if saldo:
                words.append(self._word(saldo, 506.40, 565.92, y))

            line = f"{day} {desc} {ref} {retiro} {deposito} {saldo}".strip()
            text_parts.append(line)
            y += 10

            # Línea de continuación de referencia
            if ref2:
                words.append(self._word(ref2, 314.60, 336.20, y))
                text_parts.append(ref2)
                y += 10

        return PageText(
            page_num=1,
            text="\n".join(text_parts),
            words=words,
        )

    def test_deposito_transferencia_bpi(self, parser):
        """Transferencia BPI con referencia en 2 líneas → depósito.

        Patrón real: referencia "13651011" en línea 1 + "41234" en línea 2.
        El monto aparece en columna Depósito/Abono (x0≈431).
        """
        page = self._make_page_with_real_coords(
            movements=[
                {
                    "day": "03",
                    "desc": "TRANSFERENCIA BPI DESDE LA CUENTA 9798",
                    "ref": "13651011",
                    "deposito": "$ 40,000.00",
                    "saldo": " $ 11,687,976.35",
                    "ref2": "41234",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.tipo == "deposito"
        assert mov.deposito == Decimal("40000.00")
        assert mov.fecha == date(2025, 11, 3)
        assert "13651011" in mov.referencia
        assert "41234" in mov.referencia
        assert mov.concepto == "TRANSFERENCIA BPI DESDE LA CUENTA 9798"

    def test_retiro_comision_con_iva(self, parser):
        """COMISION e IVA son retiros consecutivos con refs diferentes.

        COMISION: x0=366, monto $1,309.00 → retiro
        I.V.A.:   x0=372, monto $209.44 → retiro
        """
        page = self._make_page_with_real_coords(
            movements=[
                {
                    "day": "14",
                    "desc": "COMISION X SERVICIO GBS",
                    "ref": "16922999",
                    "retiro": "$ 1,309.00",
                    "saldo": " $ 12,188,048.49",
                },
                {
                    "day": "14",
                    "desc": "I.V.A.",
                    "ref": "11140000",
                    "retiro": "$ 209.44",
                    "saldo": " $ 12,187,839.05",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        assert resultado.movimientos[0].retiro == Decimal("1309.00")
        assert resultado.movimientos[0].concepto == "COMISION X SERVICIO GBS"
        assert resultado.movimientos[1].retiro == Decimal("209.44")
        assert resultado.movimientos[1].concepto == "I.V.A."

    def test_deposito_interes_y_retiro_isr(self, parser):
        """PAGO DE INTERES NOMINAL → depósito, I.S.R. RETENIDO → retiro.

        Estos movimientos tienen referencia de una sola línea (sin ref2).
        """
        page = self._make_page_with_real_coords(
            movements=[
                {
                    "day": "28",
                    "desc": "PAGO DE INTERES NOMINAL",
                    "ref": "11280001",
                    "deposito": "$ 29,921.22",
                    "saldo": " $ 12,863,610.87",
                },
                {
                    "day": "28",
                    "desc": "I.S.R. RETENIDO",
                    "ref": "11280001",
                    "retiro": "$ 5,019.07",
                    "saldo": " $ 12,858,591.80",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        assert resultado.movimientos[0].tipo == "deposito"
        assert resultado.movimientos[0].deposito == Decimal("29921.22")
        assert resultado.movimientos[1].tipo == "retiro"
        assert resultado.movimientos[1].retiro == Decimal("5019.07")

    def test_multipagina_depositos_continuos(self, parser):
        """Movimientos distribuidos en 2 páginas se combinan.

        La página 2 del PDF real repite el header de la tabla y continúa
        con más movimientos. El parser debe procesar ambas páginas.
        """
        page1 = self._make_page_with_real_coords(
            movements=[
                {
                    "day": "03",
                    "desc": "TRANSFERENCIA BPI DESDE LA CUENTA 9798",
                    "ref": "13651011",
                    "deposito": "$ 40,000.00",
                    "saldo": " $ 11,687,976.35",
                    "ref2": "41234",
                },
            ]
        )
        page2 = self._make_page_with_real_coords(
            movements=[
                {
                    "day": "13",
                    "desc": "TRANSFERENCIA BPI DESDE LA CUENTA 9798",
                    "ref": "13651011",
                    "deposito": "$ 85,739.82",
                    "saldo": " $ 12,134,357.49",
                    "ref2": "41234",
                },
            ],
            header_y=80.0,
            start_y=100.0,
        )
        page2 = PageText(page_num=2, text=page2.text, words=page2.words)

        resultado = parser.parse([page1, page2], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        assert resultado.movimientos[0].fecha == date(2025, 11, 3)
        assert resultado.movimientos[0].deposito == Decimal("40000.00")
        assert resultado.movimientos[1].fecha == date(2025, 11, 13)
        assert resultado.movimientos[1].deposito == Decimal("85739.82")

    def test_monto_con_centavos_no_redondea(self, parser):
        """Montos como $14,698.12 y $522.70 preservan centavos exactos."""
        page = self._make_page_with_real_coords(
            movements=[
                {
                    "day": "10",
                    "desc": "TRANSFERENCIA BPI",
                    "ref": "111",
                    "deposito": "$ 14,698.12",
                    "saldo": " $ 12,008,617.67",
                    "ref2": "41234",
                },
                {
                    "day": "26",
                    "desc": "TRANSFERENCIA BPI",
                    "ref": "222",
                    "deposito": "$ 522.70",
                    "saldo": " $ 12,638,361.75",
                    "ref2": "41234",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].deposito == Decimal("14698.12")
        assert resultado.movimientos[1].deposito == Decimal("522.70")

    def test_multiples_movimientos_mismo_dia(self, parser):
        """Varios movimientos en el mismo día se extraen individualmente.

        El día 10 del PDF real tiene 3 depósitos consecutivos.
        """
        page = self._make_page_with_real_coords(
            movements=[
                {
                    "day": "10",
                    "desc": "TRANSFERENCIA BPI DESDE LA CUENTA 9798",
                    "ref": "13651011",
                    "deposito": "$ 45,000.00",
                    "saldo": " $ 11,973,919.55",
                    "ref2": "41234",
                },
                {
                    "day": "10",
                    "desc": "TRANSFERENCIA BPI DESDE LA CUENTA 9798",
                    "ref": "13651011",
                    "deposito": "$ 20,000.00",
                    "saldo": " $ 11,993,919.55",
                    "ref2": "41234",
                },
                {
                    "day": "10",
                    "desc": "TRANSFERENCIA BPI DESDE LA CUENTA 9798",
                    "ref": "13651011",
                    "deposito": "$ 14,698.12",
                    "saldo": " $ 12,008,617.67",
                    "ref2": "41234",
                },
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 3
        assert all(m.fecha == date(2025, 11, 10) for m in resultado.movimientos)
        assert resultado.movimientos[0].deposito == Decimal("45000.00")
        assert resultado.movimientos[1].deposito == Decimal("20000.00")
        assert resultado.movimientos[2].deposito == Decimal("14698.12")

    def test_cuenta_real_10_digitos(self, parser):
        """Cuenta real HSBC: 4007185804 (10 dígitos)."""
        page = self._make_page_with_real_coords(movements=[])
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.cuenta == "4007185804"

    def test_periodo_noviembre_2025(self, parser):
        """Periodo del PDF real: 01/11/2025 al 30/11/2025."""
        page = self._make_page_with_real_coords(movements=[])
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2025
        assert resultado.mes == 11
