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

    def test_retiro_por_posicion_x_2_montos(self, parser):
        """Con 2 montos, X en rango retiro (445-515) → retiro.

        La posición X es el clasificador primario. Si el monto
        está en la columna de retiros (x0≈463), es retiro
        independientemente del concepto.
        """
        page = self._make_banorte_page(
            concepto_words=["PAGO", "SERVICIO"],
            montos=[("1,500.00", 463.0), ("118,500.00", 530.0)],
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

    # === Tests de clasificación por X en caso 2 montos (bug #45) ===
    #
    # BUG ORIGINAL: con 2 montos, solo se usaban keywords para
    # clasificar. "DEP.EFECTIVO" no matchea "DEPOSITO" → se
    # clasificaba como retiro. Pero la coordenada X indicaba
    # claramente columna depósito (x0≈389 vs retiro x0≈463).
    #
    # FIX: en 2 montos, X position es el clasificador primario.
    # Keywords son fallback solo si X no cae en ningún rango.

    def test_dep_efectivo_2_montos_x_deposito(self, parser):
        """DEP.EFECTIVO con X en columna depósito → depósito.

        Este es el caso real del bug: el concepto "DEP.EFECTIVO"
        no empieza con "DEPOSITO" (es "DEP." ≠ "DEPOSITO"), pero
        su monto está en x0≈389 que es columna de depósitos.
        El fix usa X primero → depósito correcto.
        """
        page = self._make_banorte_page(
            concepto_words=["DEP.EFECTIVO"],
            montos=[("43,700.00", 389.6), ("31,763,734.72", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("43700.00")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_spei_compensacion_2_montos_x_deposito(self, parser):
        """SPEI COMPENSACION con X en columna depósito → depósito.

        Otro caso real del bug: "SPEI 01042025 COMPENSACION DESFASE"
        no empieza con "SPEI RECIBIDO" ni contiene "SPEI RECIBIDO",
        pero x0=405 cae en rango depósito (370-445).
        """
        page = self._make_banorte_page(
            concepto_words=["SPEI", "01042025", "COMPENSACION", "DESFASE"],
            montos=[("0.04", 405.0), ("31,747,609.37", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("0.04")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_cheque_pagado_2_montos_x_retiro(self, parser):
        """CHEQUE PAGADO con X en columna retiro → retiro.

        Verifica que retiros legítimos siguen funcionando: el monto
        está en x0≈463 (columna retiro, rango 445-515).
        """
        page = self._make_banorte_page(
            concepto_words=["CHEQUE", "PAGADO", "0125326"],
            montos=[("2,075.93", 463.1), ("31,761,658.79", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("2075.93")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

    def test_keyword_fallback_x_fuera_rango(self, parser):
        """Si X no cae en ningún rango → fallback a keywords.

        Cuando la posición X del monto no está ni en rango
        depósito (370-445) ni en rango retiro (445-515),
        se usa el concepto para decidir. "DEPOSITO" → depósito.
        """
        page = self._make_banorte_page(
            concepto_words=["DEPOSITO", "EN", "EFECTIVO"],
            montos=[("5,000.00", 350.0), ("125,000.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("5000.00")
        assert mov.tipo == "deposito"

    def test_keyword_fallback_retiro_x_fuera_rango(self, parser):
        """Si X fuera de rango y concepto NO es keyword → retiro."""
        page = self._make_banorte_page(
            concepto_words=["CARGO", "COMISION"],
            montos=[("500.00", 350.0), ("119,500.00", 530.0)],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("500.00")
        assert mov.tipo == "retiro"

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


# ============================================================
# Tests de limpieza de footer/trailer en conceptos
# ============================================================


class TestBanorteFooterTrailerCleanup:
    """Tests que validan que el footer de página y las secciones
    informativas del final del documento NO contaminen los conceptos.

    BUG: El loop de continuación multi-línea solo se detenía al
    encontrar una línea con fecha. Todo lo demás se agregaba al
    concepto del último movimiento. Esto causaba que:

    1. El footer de cada página (teléfonos, URLs del banco) se
       pegara al último movimiento de cada hoja:
       "PAGO SERVICIO Línea Directa para su empresa: Ciudad de
       México: (55) 5140 5640 | Monterrey: (81) 8156 9640..."

    2. La sección "OTROS▼ Cargos Objetados en el Periodo..." al
       final del documento se pegara al último movimiento total.

    FIX: Se agregaron marcadores de parada (_CONTINUATION_STOP_MARKERS)
    que detienen la captura cuando detectan contenido de footer/trailer.
    """

    @pytest.fixture
    def parser(self):
        return BanorteParser()

    def _make_word(self, text: str, x0: float, top: float) -> WordInfo:
        return WordInfo(
            text=text,
            x0=x0,
            x1=x0 + len(text) * 7,
            top=top,
            bottom=top + 12,
        )

    def _page_with_footer(
        self,
        footer_words: list[str],
        concepto_words: list[str] | None = None,
    ) -> PageText:
        """Crea página con un movimiento seguido de líneas de footer.

        Simula el layout real de Banorte donde después del último
        movimiento de la página aparece el pie de página con info
        de contacto del banco.

        Args:
            footer_words: Lista de palabras del footer. Cada palabra
                se coloca en una línea separada (Y distinta) para
                simular el footer multi-línea real.
            concepto_words: Palabras del concepto del movimiento.
        """
        if concepto_words is None:
            concepto_words = ["PAGO", "SERVICIO", "LUZ"]

        words: list[WordInfo] = []
        text_parts: list[str] = []

        # Encabezado mínimo
        y = 50.0
        words.append(self._make_word("BANORTE", 50, y))
        words.append(self._make_word("CUENTA", 50, y + 15))
        words.append(self._make_word("PRODUCTIVA", 110, y + 15))
        words.append(self._make_word("ESPECIAL", 190, y + 15))
        words.append(self._make_word("0987654321", 260, y + 15))
        words.append(self._make_word("Periodo", 50, y + 30))
        words.append(self._make_word("Del", 110, y + 30))
        words.append(self._make_word("01-OCT-24", 140, y + 30))
        words.append(self._make_word("Al", 220, y + 30))
        words.append(self._make_word("31-OCT-24", 240, y + 30))
        y += 45
        words.append(self._make_word("DETALLE", 50, y))
        words.append(self._make_word("DE", 110, y))
        words.append(self._make_word("MOVIMIENTOS", 130, y))
        y += 20

        text_parts.append("BANORTE")
        text_parts.append("CUENTA PRODUCTIVA ESPECIAL 0987654321")
        text_parts.append("Periodo Del 01-OCT-24 Al 31-OCT-24")
        text_parts.append("DETALLE DE MOVIMIENTOS")

        # Movimiento
        mov_y = y
        words.append(self._make_word("15-OCT-24", 50, mov_y))
        x = 140.0
        for palabra in concepto_words:
            words.append(self._make_word(palabra, x, mov_y))
            x += len(palabra) * 7 + 5
        words.append(self._make_word("1,500.00", 460, mov_y))
        words.append(self._make_word("118,500.00", 530, mov_y))

        mov_text = f"15-OCT-24 {' '.join(concepto_words)} 1,500.00 118,500.00"
        text_parts.append(mov_text)
        y = mov_y + 20

        # Footer/trailer: cada elemento en su propia línea Y
        for footer_line in footer_words:
            for i, word in enumerate(footer_line.split()):
                words.append(self._make_word(word, 50 + i * 60, y))
            text_parts.append(footer_line)
            y += 15

        return PageText(
            page_num=1,
            text="\n".join(text_parts),
            words=words,
        )

    # --- Tests del footer de página ---

    def test_footer_linea_directa_no_contamina(self, parser):
        """El footer 'Línea Directa para su empresa...' NO se pega
        al concepto del último movimiento de la página."""
        page = self._page_with_footer(
            footer_words=[
                "Línea Directa para su empresa:",
                "Ciudad de México: (55) 5140 5640",
                "Monterrey: (81) 8156 9640",
                "Guadalajara: (33) 3669 9040",
                "Resto del país: 800 DIRECTA (3473282)",
                "Visita nuestra página: www.banorte.com",
                "Banco Mercantil del Norte",
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        concepto = resultado.movimientos[0].concepto
        assert "Línea Directa" not in concepto
        assert "Ciudad de México" not in concepto
        assert "www.banorte" not in concepto
        assert "Banco Mercan" not in concepto
        assert "800 DIRECTA" not in concepto
        assert "PAGO SERVICIO LUZ" in concepto

    def test_footer_sin_acento_no_contamina(self, parser):
        """Variante sin acentos (OCR) tampoco contamina."""
        page = self._page_with_footer(
            footer_words=[
                "Linea Directa para su empresa:",
                "Ciudad de Mexico: (55) 5140 5640",
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        concepto = resultado.movimientos[0].concepto
        assert "Linea Directa" not in concepto
        assert "Ciudad de Mexico" not in concepto

    # --- Tests del trailer del documento ---

    def test_trailer_cargos_objetados_no_contamina(self, parser):
        """La sección 'OTROS▼ Cargos Objetados...' al final del
        documento NO se pega al último movimiento."""
        page = self._page_with_footer(
            footer_words=[
                "OTROS▼ Cargos Objetados en el Periodo",
                "Folio Fecha Tipo de Cargo Monto Fecha de Cargo",
                "N/A N/A N/A N/A N/A",
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        concepto = resultado.movimientos[0].concepto
        assert "Cargos Objetados" not in concepto
        assert "OTROS" not in concepto
        assert "Folio Fecha Tipo" not in concepto
        assert "N/A" not in concepto

    def test_trailer_informe_depositos_no_contamina(self, parser):
        """'Informe de Depósitos en efectivo' no contamina."""
        page = self._page_with_footer(
            footer_words=[
                "Informe de Depósitos en efectivo realizados",
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        concepto = resultado.movimientos[0].concepto
        assert "Informe de Dep" not in concepto

    # --- Test de que conceptos multi-línea legítimos SÍ funcionan ---

    def test_continuacion_legitima_si_se_captura(self, parser):
        """Líneas de continuación legítimas (referencias, claves)
        SÍ se siguen agregando al concepto.

        Este test asegura que el fix no es demasiado agresivo.
        Solo se detiene con marcadores de footer/trailer, no con
        cualquier línea sin fecha.
        """
        words: list[WordInfo] = []
        text_parts: list[str] = []

        y = 50.0
        words.append(self._make_word("BANORTE", 50, y))
        words.append(self._make_word("CUENTA", 50, y + 15))
        words.append(self._make_word("PRODUCTIVA", 110, y + 15))
        words.append(self._make_word("ESPECIAL", 190, y + 15))
        words.append(self._make_word("0987654321", 260, y + 15))
        words.append(self._make_word("Periodo", 50, y + 30))
        words.append(self._make_word("Del", 110, y + 30))
        words.append(self._make_word("01-OCT-24", 140, y + 30))
        words.append(self._make_word("Al", 220, y + 30))
        words.append(self._make_word("31-OCT-24", 240, y + 30))
        y += 45
        words.append(self._make_word("DETALLE", 50, y))
        words.append(self._make_word("DE", 110, y))
        words.append(self._make_word("MOVIMIENTOS", 130, y))
        y += 20

        text_parts.extend(
            [
                "BANORTE",
                "CUENTA PRODUCTIVA ESPECIAL 0987654321",
                "Periodo Del 01-OCT-24 Al 31-OCT-24",
                "DETALLE DE MOVIMIENTOS",
            ]
        )

        # Movimiento con concepto multi-línea legítimo
        mov_y = y
        words.append(self._make_word("15-OCT-24", 50, mov_y))
        words.append(self._make_word("SPEI", 140, mov_y))
        words.append(self._make_word("RECIBIDO", 180, mov_y))
        words.append(self._make_word("50,000.00", 400, mov_y))
        words.append(self._make_word("170,000.00", 530, mov_y))
        text_parts.append("15-OCT-24 SPEI RECIBIDO 50,000.00 170,000.00")

        # Línea de continuación legítima (referencia)
        cont_y = mov_y + 15
        words.append(self._make_word("REFERENCIA:", 140, cont_y))
        words.append(self._make_word("ABC123", 230, cont_y))
        words.append(self._make_word("CVE", 300, cont_y))
        words.append(self._make_word("RAST:", 330, cont_y))
        words.append(self._make_word("XYZ789", 370, cont_y))
        text_parts.append("REFERENCIA: ABC123 CVE RAST: XYZ789")

        page = PageText(
            page_num=1,
            text="\n".join(text_parts),
            words=words,
        )

        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert "REFERENCIA:" in mov.concepto
        assert mov.referencia == "ABC123"
        assert mov.deposito == Decimal("50000.00")

    # --- Test combinado: continuación + footer ---

    def test_continuacion_legitima_seguida_de_footer(self, parser):
        """Un concepto multi-línea legítimo seguido de footer:
        la referencia SÍ se captura, el footer NO."""
        words: list[WordInfo] = []
        text_parts: list[str] = []

        y = 50.0
        words.append(self._make_word("BANORTE", 50, y))
        words.append(self._make_word("CUENTA", 50, y + 15))
        words.append(self._make_word("PRODUCTIVA", 110, y + 15))
        words.append(self._make_word("ESPECIAL", 190, y + 15))
        words.append(self._make_word("0987654321", 260, y + 15))
        words.append(self._make_word("Periodo", 50, y + 30))
        words.append(self._make_word("Del", 110, y + 30))
        words.append(self._make_word("01-OCT-24", 140, y + 30))
        words.append(self._make_word("Al", 220, y + 30))
        words.append(self._make_word("31-OCT-24", 240, y + 30))
        y += 45
        words.append(self._make_word("DETALLE", 50, y))
        words.append(self._make_word("DE", 110, y))
        words.append(self._make_word("MOVIMIENTOS", 130, y))
        y += 20

        text_parts.extend(
            [
                "BANORTE",
                "CUENTA PRODUCTIVA ESPECIAL 0987654321",
                "Periodo Del 01-OCT-24 Al 31-OCT-24",
                "DETALLE DE MOVIMIENTOS",
            ]
        )

        # Movimiento
        mov_y = y
        words.append(self._make_word("15-OCT-24", 50, mov_y))
        words.append(self._make_word("PAGO", 140, mov_y))
        words.append(self._make_word("SERVICIO", 185, mov_y))
        words.append(self._make_word("1,500.00", 460, mov_y))
        words.append(self._make_word("118,500.00", 530, mov_y))
        text_parts.append("15-OCT-24 PAGO SERVICIO 1,500.00 118,500.00")

        # Continuación legítima
        cont_y = mov_y + 15
        words.append(self._make_word("REFERENCIA:", 140, cont_y))
        words.append(self._make_word("REF999", 230, cont_y))
        text_parts.append("REFERENCIA: REF999")

        # Footer (NO debe capturarse)
        footer_y = cont_y + 25
        for i, w in enumerate(["Línea", "Directa", "para", "su", "empresa:"]):
            words.append(self._make_word(w, 50 + i * 60, footer_y))
        text_parts.append("Línea Directa para su empresa:")

        page = PageText(
            page_num=1,
            text="\n".join(text_parts),
            words=words,
        )

        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        # Continuación legítima SÍ se captura
        assert "REFERENCIA:" in mov.concepto
        assert mov.referencia == "REF999"
        # Footer NO se captura
        assert "Línea Directa" not in mov.concepto
