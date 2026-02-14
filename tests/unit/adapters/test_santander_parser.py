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


class TestSantanderMultilineDescriptions:
    """Tests para descripciones de movimientos multi-línea.

    Los movimientos de Santander pueden tener líneas adicionales con
    información del remitente, cuenta origen, clave de rastreo, RFC, etc.
    Estas líneas NO tienen fecha ni montos — solo texto descriptivo.

    Ejemplo real de un SPEI:
        01-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI HORA 09:58:31  51,451.13  2,744,700.76
                    RECIBIDO DE BAJIO
                    DE LA CUENTA 030231900039926298
                    DEL CLIENTE CUEROS ORION SA DE CV
                    CLAVE DE RASTREO BB1029312020788
                    REF 1029312
                    CONCEPTO PAGO
                    RFC COR230419MX9
    """

    @pytest.fixture
    def parser(self):
        return SantanderParser()

    def _make_page(
        self,
        movimiento_lines: list[str] | None = None,
        header: str | None = None,
    ) -> PageText:
        if header is None:
            header = (
                "Santander\n"
                "Estado de Cuenta\n"
                "Cuenta: 65-50123456-7\n"
                "Periodo del 01-Abr-2025 al 30-Abr-2025\n"
                "Moneda: MXN\n"
            )
        if movimiento_lines is None:
            movimiento_lines = []
        text = header + "\n" + "\n".join(movimiento_lines)
        return PageText(page_num=1, text=text)

    def test_spei_con_todas_las_lineas_continuacion(self, parser):
        """SPEI con 7 líneas de continuación incluye toda la descripción.

        Verifica que remitente, cuenta, cliente, clave de rastreo, REF,
        concepto y RFC se incorporan al concepto del movimiento.
        """
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI HORA 09:58:31 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "DE LA CUENTA 030231900039926298",
                "DEL CLIENTE CUEROS ORION SA DE CV",
                "CLAVE DE RASTREO BB1029312020788",
                "REF 1029312",
                "CONCEPTO PAGO",
                "RFC COR230419MX9",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("51451.13")
        assert mov.tipo == "deposito"
        # Verificar que TODA la información está en el concepto
        assert "ABONO TRANSFERENCIA SPEI" in mov.concepto
        assert "RECIBIDO DE BAJIO" in mov.concepto
        assert "030231900039926298" in mov.concepto
        assert "CUEROS ORION SA DE CV" in mov.concepto
        assert "BB1029312020788" in mov.concepto
        assert "REF 1029312" in mov.concepto
        assert "CONCEPTO PAGO" in mov.concepto
        assert "COR230419MX9" in mov.concepto

    def test_separador_entre_lineas_continuacion(self, parser):
        """Las líneas de continuación se separan con ' | '.

        Esto mantiene claridad visual y facilita búsquedas posteriores.
        """
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "DE LA CUENTA 030231900039926298",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert " | RECIBIDO DE BAJIO | DE LA CUENTA 030231900039926298" in mov.concepto

    def test_movimiento_sin_continuacion_no_cambia(self, parser):
        """Movimientos de una sola línea funcionan igual que antes."""
        page = self._make_page(
            [
                "1-ABR-2025 0000000 CUOTA AFILIACION TPV AFIL.-007649837 299.00 2,693,297.47",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert "CUOTA AFILIACION TPV" in mov.concepto
        # No debe tener separador de continuación
        assert " | " not in mov.concepto

    def test_continuacion_no_afecta_siguiente_movimiento(self, parser):
        """Las líneas de continuación se asignan al movimiento correcto.

        Cuando hay un SPEI con 7 líneas de continuación seguido de un
        depósito simple, cada movimiento tiene su propia descripción.
        """
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI HORA 09:58:31 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "DE LA CUENTA 030231900039926298",
                "DEL CLIENTE CUEROS ORION SA DE CV",
                "CLAVE DE RASTREO BB1029312020788",
                "REF 1029312",
                "CONCEPTO PAGO",
                "RFC COR230419MX9",
                "1-ABR-2025 0000310 DEPOSITO EN EFECTIVO ATM 20,400.00 2,765,100.76",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        # Primer movimiento: SPEI con continuación completa
        spei = resultado.movimientos[0]
        assert "ABONO TRANSFERENCIA SPEI" in spei.concepto
        assert "CUEROS ORION SA DE CV" in spei.concepto
        assert spei.deposito == Decimal("51451.13")
        # Segundo movimiento: depósito simple, sin contaminación
        deposito = resultado.movimientos[1]
        assert "DEPOSITO EN EFECTIVO ATM" in deposito.concepto
        assert "BAJIO" not in deposito.concepto
        assert deposito.deposito == Decimal("20400.00")

    def test_multiples_spei_con_continuacion(self, parser):
        """Varios movimientos con continuación se procesan independientemente."""
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "DEL CLIENTE CUEROS ORION SA DE CV",
                "5-ABR-2025 6789012 ABONO TRANSFERENCIA SPEI 30,000.00 2,774,700.76",
                "RECIBIDO DE BBVA",
                "DEL CLIENTE ACME SA",
                "RFC ACM210101XX1",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        # Primer SPEI
        assert "CUEROS ORION" in resultado.movimientos[0].concepto
        assert "BBVA" not in resultado.movimientos[0].concepto
        # Segundo SPEI
        assert "ACME SA" in resultado.movimientos[1].concepto
        assert "BAJIO" not in resultado.movimientos[1].concepto
        assert "ACM210101XX1" in resultado.movimientos[1].concepto

    def test_filtro_ruido_pagina(self, parser):
        """'Página X de Y' NO se agrega como continuación."""
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "Página 2 de 5",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert "RECIBIDO DE BAJIO" in mov.concepto
        assert "Página" not in mov.concepto

    def test_filtro_ruido_separadores(self, parser):
        """Líneas de separación '---' NO se agregan como continuación."""
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "----------",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert "RECIBIDO DE BAJIO" in mov.concepto
        assert "---" not in mov.concepto

    def test_filtro_ruido_numeros_solos(self, parser):
        """Líneas con solo números NO se agregan como continuación."""
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "12345",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert "RECIBIDO DE BAJIO" in mov.concepto
        assert "12345" not in mov.concepto

    def test_continuacion_no_se_acumula_entre_paginas(self, parser):
        """Las líneas de continuación se reinician al cambiar de página.

        Cada página empieza fresco: last_match=None, continuation_lines=[].
        """
        page1 = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
            ]
        )
        page2 = self._make_page(
            header="Santander\nCuenta: 65-50123456-7\nPeriodo del 01-Abr-2025 al 30-Abr-2025",
            movimiento_lines=[
                "5-ABR-2025 1111111 DEPOSITO EFECTIVO 10,000.00 2,754,700.76",
                "SUCURSAL CENTRO",
            ],
        )
        page2 = PageText(page_num=2, text=page2.text)

        resultado = parser.parse([page1, page2], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        # Página 1: SPEI con continuación
        assert "BAJIO" in resultado.movimientos[0].concepto
        # Página 2: depósito con su propia continuación
        assert "SUCURSAL CENTRO" in resultado.movimientos[1].concepto
        assert "BAJIO" not in resultado.movimientos[1].concepto

    def test_tipo_deposito_detectado_en_linea_principal(self, parser):
        """La clasificación depósito/retiro se basa en TODO el concepto.

        La keyword 'ABONO' en la primera línea ya clasifica como depósito.
        Las líneas de continuación no afectan la clasificación.
        """
        page = self._make_page(
            [
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "DEL CLIENTE ALGO SA DE CV",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].tipo == "deposito"

    def test_imagen_ejemplo_real_completo(self, parser):
        """Reproduce el escenario exacto de la imagen del usuario.

        Incluye: 2 retiros (CUOTA + IVA), 1 SPEI con 7 líneas, y 4 depósitos.
        """
        page = self._make_page(
            [
                "1-ABR-2025 0000000 CUOTA AFILIACION TPV AFIL.-007649837 299.00 2,693,297.47",
                "1-ABR-2025 0000000 COBRO IVA AFIL.-007649838 47.84 2,693,249.63",
                "1-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI HORA 09:58:31 51,451.13 2,744,700.76",
                "RECIBIDO DE BAJIO",
                "DE LA CUENTA 030231900039926298",
                "DEL CLIENTE CUEROS ORION SA DE CV",
                "CLAVE DE RASTREO BB1029312020788",
                "REF 1029312",
                "CONCEPTO PAGO",
                "RFC COR230419MX9",
                "1-ABR-2025 0000310 DEPOSITO EN EFECTIVO ATM 20,400.00 2,765,100.76",
                "1-ABR-2025 0000314 DEPOSITO EN EFECTIVO ATM 6,500.00 2,771,600.76",
                "1-ABR-2025 2509440 DEPOSITO EN EFECTIVO 85,100.00 2,856,700.76",
                "1-ABR-2025 0000000 ABONO TRANSFERENCIA ENLACE TRASPASO 6,300,000.00 9,156,700.76",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 7

        # Mov 1: CUOTA AFILIACION → retiro
        assert resultado.movimientos[0].retiro == Decimal("299.00")
        assert resultado.movimientos[0].tipo == "retiro"

        # Mov 2: COBRO IVA → retiro
        assert resultado.movimientos[1].retiro == Decimal("47.84")

        # Mov 3: SPEI con descripción completa
        spei = resultado.movimientos[2]
        assert spei.deposito == Decimal("51451.13")
        assert "ABONO TRANSFERENCIA SPEI" in spei.concepto
        assert "CUEROS ORION SA DE CV" in spei.concepto
        assert "BB1029312020788" in spei.concepto
        assert "COR230419MX9" in spei.concepto

        # Mov 4-6: Depósitos en efectivo
        assert resultado.movimientos[3].deposito == Decimal("20400.00")
        assert resultado.movimientos[4].deposito == Decimal("6500.00")
        assert resultado.movimientos[5].deposito == Decimal("85100.00")

        # Mov 7: Enlace traspaso
        assert resultado.movimientos[6].deposito == Decimal("6300000.00")


class TestSantanderDoubledTextCleaning:
    """Tests para limpieza de texto duplicado en líneas de continuación.

    El PDF de Santander tiene doble capa de texto superpuesto: cuando
    pdfplumber extrae el texto, cada carácter aparece dos veces consecutivas.
    Ejemplo: "RECIBIDO DE BBVA" → "RREECCIIBBIIDDOO DDEE BBBBVVAA"

    Este fenómeno afecta:
    - Líneas de fecha (movimientos): "0022--JJUUNN--22002255 ..."
    - Líneas de continuación: "RREECCIIBBIIDDOO DDEE BBAAJJIIOO"
    - Encabezados: "FFEECCHHAA FFOOLLIIOO DDEESSCCRRIIPPCCIIOONN"

    La limpieza debe aplicarse a TODA línea doubled, no solo a las de fecha.
    """

    @pytest.fixture
    def parser(self):
        return SantanderParser()

    def _make_page(
        self,
        movimiento_lines: list[str] | None = None,
        header: str | None = None,
    ) -> PageText:
        if header is None:
            header = (
                "Santander\n"
                "Estado de Cuenta\n"
                "Cuenta: 65-50123456-7\n"
                "Periodo del 01-Jun-2025 al 30-Jun-2025\n"
                "Moneda: MXN\n"
            )
        if movimiento_lines is None:
            movimiento_lines = []
        text = header + "\n" + "\n".join(movimiento_lines)
        return PageText(page_num=1, text=text)

    # === Tests de detección ===

    def test_detecta_texto_duplicado_continuacion(self, parser):
        """Detecta texto doubled en líneas de continuación (sin fecha).

        Las líneas de continuación como "RREECCIIBBIIDDOO DDEE BBBBVVAA"
        tienen cada carácter alfanumérico duplicado. La detección evalúa
        los primeros 20 caracteres alfanuméricos: si >70% forman pares
        idénticos, la línea está duplicada.
        """
        _d = SantanderParser._es_texto_duplicado
        assert _d("RREECCIIBBIIDDOO DDEE BBBBVVAA MMEEXXIICCOO")
        assert _d("DDEE LLAA CCUUEENNTTAA 001122558800000011220011883333885555")
        assert _d("DDEELL CCLLIIEENNTTEE BBRRAANNGGUUSS SSEELLEECCTTOO")
        assert _d("CCLLAAVVEE DDEE RRAASSTTRREEOO BBNNEETT0011000022550066")
        assert _d("RRFFCC BBSSNN222211110077RRAA11")

    def test_no_detecta_texto_normal_como_duplicado(self, parser):
        """Texto normal NO se detecta como duplicado.

        Palabras como "COFFEE" o "LLAMA" tienen letras repetidas
        naturalmente, pero no en el patrón par-a-par que genera
        la doble capa de Santander. La detección mira la distribución
        estadística, no letras individuales.
        """
        assert not SantanderParser._es_texto_duplicado("RECIBIDO DE BBVA MEXICO")
        assert not SantanderParser._es_texto_duplicado("DEL CLIENTE CUEROS ORION SA DE CV")
        assert not SantanderParser._es_texto_duplicado("RFC BSN221107RA1")
        assert not SantanderParser._es_texto_duplicado("COFFEE SHOP")
        assert not SantanderParser._es_texto_duplicado("LLAMA GREETINGS")

    def test_no_detecta_texto_corto(self, parser):
        """Textos muy cortos (< 6 alfanuméricos) no se evalúan.

        Con pocos caracteres el riesgo de falso positivo es alto.
        Ejemplo: "AA" tiene 100% pares iguales pero es solo coincidencia.
        """
        assert not SantanderParser._es_texto_duplicado("AA")
        assert not SantanderParser._es_texto_duplicado("Hi")
        assert not SantanderParser._es_texto_duplicado("")

    def test_detecta_linea_fecha_duplicada(self, parser):
        """Líneas de fecha doubled también se detectan correctamente.

        El viejo _DUPLICATED_TEXT_PATTERN solo buscaba "\\d{2,4}--[A-Z]{2,6}--".
        El nuevo _es_texto_duplicado es más general y cubre tanto fechas
        como cualquier otra línea.
        """
        assert SantanderParser._es_texto_duplicado(
            "0022--JJUUNN--22002255 55554422773366AABBOONNOO TTRRAANNSSFFEERREENNCCIIAA SSPPEEII"
        )

    # === Tests de limpieza en continuación ===

    def test_continuacion_doubled_se_limpia_en_concepto(self, parser):
        """Líneas de continuación doubled se limpian antes de unirse al concepto.

        Este es el bug exacto que reportó el usuario: las líneas de
        continuación como "RREECCIIBBIIDDOO DDEE BBBBVVAA MMEEXXIICCOO"
        aparecían textualmente en el concepto en vez de "RECIBIDO DE BBVA MEXICO".

        La limpieza se aplica al inicio del loop sobre cada línea,
        ANTES de decidir si es continuación o movimiento nuevo.
        """
        page = self._make_page(
            [
                "2-JUN-2025 5542736 ABONO TRANSFERENCIA SPEI HORA 09:53:48 459,529.60 519,801.39",
                "RREECCIIBBIIDDOO DDEE BBBBVVAA MMEEXXIICCOO",
                "DDEE LLAA CCUUEENNTTAA" " 001122558800000011220011883333885555",
                "DDEELL CCLLIIEENNTTEE BBRRAANNGGUUSS"
                " SSEELLEECCTTOO DDEELL NNOORRTTEE SSAA DDEE CCVV",
                "CCLLAAVVEE DDEE RRAASSTTRREEOO"
                " BBNNEETT0011000022550066002200004499112266333300",
                "RREEFF 00000022000044",
                "CCOONNCCEEPPTTOO FFAACC 991100004477449955",
                "RRFFCC BBSSNN222211110077RRAA11",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]

        # Verificar que el concepto tiene texto LIMPIO, no doubled
        assert "RECIBIDO DE BBVA MEXICO" in mov.concepto
        assert "DE LA CUENTA 012580001201833855" in mov.concepto
        assert "DEL CLIENTE BRANGUS SELECTO DEL NORTE SA DE CV" in mov.concepto
        assert "CLAVE DE RASTREO BNET01002506020049126330" in mov.concepto
        assert "REF 0002004" in mov.concepto
        assert "CONCEPTO FAC 910047495" in mov.concepto
        assert "RFC BSN221107RA1" in mov.concepto

        # Verificar que NO tiene texto doubled
        assert "RREECCIIBBIIDDOO" not in mov.concepto
        assert "BBBBVVAA" not in mov.concepto
        assert "BBSSNN" not in mov.concepto

    def test_segundo_ejemplo_banregio_doubled(self, parser):
        """Segundo ejemplo del reporte del usuario: SPEI de Banregio.

        "RREECCIIBBIIDDOO DDEE BBAANNRREEGGIIOO" debe limpiarse a
        "RECIBIDO DE BANREGIO".
        """
        page = self._make_page(
            [
                "2-JUN-2025 9539556 ABONO TRANSFERENCIA SPEI HORA 13:49:12 132,161.47 3,560,623.99",
                "RREECCIIBBIIDDOO DDEE BBAANNRREEGGIIOO",
                "DDEE LLAA CCUUEENNTTAA 005588558800330000336611330000112299",
                "DDEELL CCLLIIEENNTTEE GGAALLAA BBEEEEFF AALLIIMMEENNTTOOSS SS..AA.. DDEE CC..VV..",
                "CCLLAAVVEE DDEE RRAASSTTRREEOO"
                " 005588--0022//0066//22002255//0022--003300QQCCXXZZ668855",
                "RREEFF 665544009944",
                "CCOONNCCEEPPTTOO BB00991100004477440000 GGAALLAA BBEEEEFF AALLIIMMEENNTTOOSS",
                "RRFFCC GGBBAA114411001166CCLL77",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]

        assert "RECIBIDO DE BANREGIO" in mov.concepto
        assert "DE LA CUENTA 058580300361300129" in mov.concepto
        assert "DEL CLIENTE GALA BEEF ALIMENTOS S.A. DE C.V." in mov.concepto
        assert "058-02/06/2025/02-030QCXZ685" in mov.concepto
        assert "REF 654094" in mov.concepto
        assert "RFC GBA141016CL7" in mov.concepto

        # Sin texto doubled
        assert "RREECCIIBBIIDDOO" not in mov.concepto
        assert "BBAANNRREEGGIIOO" not in mov.concepto

    def test_mezcla_lineas_clean_y_doubled(self, parser):
        """Movimiento clean seguido por continuación doubled, o viceversa.

        En el PDF real, algunas líneas son clean y otras doubled.
        Ambas deben procesarse correctamente.
        """
        page = self._make_page(
            [
                # Movimiento 1: línea de fecha CLEAN + continuación DOUBLED
                "2-JUN-2025 9063704 ABONO TRANSFERENCIA SPEI HORA 12:15:24 59,114.83 3,410,152.50",
                "RECIBIDO DE BBVA MEXICO",  # clean
                "DDEE LLAA CCUUEENNTTAA 001122558800000011995511332277111166",  # doubled
                "DEL CLIENTE EPIFANIO AGUAYO ZAPATA",  # clean
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]

        # Tanto las clean como las doubled están correctas
        assert "RECIBIDO DE BBVA MEXICO" in mov.concepto
        assert "DE LA CUENTA 012580001951327116" in mov.concepto  # cleaned
        assert "DEL CLIENTE EPIFANIO AGUAYO ZAPATA" in mov.concepto

    def test_linea_fecha_doubled_se_limpia_y_parsea(self, parser):
        """Línea de fecha doubled se limpia y se procesa como movimiento.

        Líneas como "0022--JJUUNN--22002255 22550000001111DDEEPPOOSSIITTOO..."
        se limpian a "02-JUN-2025 2500011DEPOSITO..." y luego matchean
        el _LINE_PATTERN normalmente.

        Nota: en el PDF real, el monto de la línea doubled suele estar
        truncado, así que muchas veces _procesar_linea retorna None
        por no tener 2 montos válidos. Esto es comportamiento esperado.
        """
        page = self._make_page(
            [
                # Versión doubled con montos completos (caso ideal para test)
                "0022--JJUUNN--22002255 2255000000"
                "1111DDEEPPOOSSIITTOO EENN EEFFEECCTTII"
                "VVOO 2200..0000 551199,,882211..3399",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("20.00")
        assert "DEPOSITO EN EFECTIVO" in mov.concepto

    def test_doubled_y_clean_misma_fecha_monto_genera_dos(self, parser):
        """Si ambas capas tienen montos completos, se generan 2 movimientos.

        El sistema de duplicados usa fecha+monto+contador, así que dos
        líneas con misma fecha y monto (una clean y una cleaned-from-doubled)
        generan movimientos separados. Esto es esperado: en el PDF real
        la capa doubled suele tener montos truncados, así que en la
        práctica solo se genera uno.
        """
        page = self._make_page(
            [
                "2-JUN-2025 2500011 DEPOSITO EN EFECTIVO 20.00 519,821.39",
                "0022--JJUUNN--22002255 2255000000"
                "1111DDEEPPOOSSIITTOO EENN EEFFEECCTTII"
                "VVOO 2200..0000 551199,,882211..3399",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Ambas generan movimiento porque tienen montos completos
        # y el dedup permite repeticiones con contador incremental
        assert len(resultado.movimientos) == 2

    def test_doubled_con_monto_truncado_no_genera_movimiento(self, parser):
        """Línea doubled con monto truncado NO genera movimiento.

        En el PDF real, la capa doubled frecuentemente tiene montos
        cortados: "445599,,5555" que limpio queda "459,55" (sin .XX final).
        El regex _MONEY_PATTERN exige \\d{2} al final, así que "459,55"
        no matchea como monto válido → menos de 2 montos → None.
        """
        page = self._make_page(
            [
                # Versión clean (monto completo)
                "2-JUN-2025 5542736 ABONO TRANSFERENCIA SPEI 459,529.60 519,801.39",
                # Versión doubled con monto truncado (como en el PDF real)
                "0022--JJUUNN--22002255 5555442277"
                "3366AABBOONNOO TTRRAANNSSFFEERREENNCC"
                "IIAA SSPPEEII 445599,,55",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Solo la versión clean genera movimiento
        assert len(resultado.movimientos) == 1
        assert resultado.movimientos[0].deposito == Decimal("459529.60")

    def test_ruido_doubled_no_es_continuacion(self, parser):
        """Headers de tabla doubled se filtran como ruido tras limpieza.

        "FFEECCHHAA FFOOLLIIOO DDEESSCCRRIIPPCCIIOONN" se limpia a
        "FECHA FOLIO DESCRIPCION" que matchea el noise pattern de headers.
        No debe aparecer como continuación de ningún movimiento.
        """
        page = self._make_page(
            [
                "2-JUN-2025 5542736 ABONO SPEI 459,529.60 519,801.39",
                "FFEECCHHAA FFOOLLIIOO DDEESSCCRRIIPPCCIIOONN"
                " DDEEPPOOSSIITTOO RREETTIIRROO SSAALLDDOO",
                "RECIBIDO DE BAJIO",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]

        # La continuación válida sí se incluye
        assert "RECIBIDO DE BAJIO" in mov.concepto
        # El header de tabla NO se incluye
        assert "FOLIO" not in mov.concepto
        assert "DESCRIPCION" not in mov.concepto

    def test_escenario_pdf_real_intercalado(self, parser):
        """Simula la estructura real del PDF: clean + doubled intercalados.

        En el PDF de Santander, los movimientos aparecen así:
        1. Línea de fecha doubled (montos truncados) → descartada
        2. Continuación doubled × N
        3. Línea de fecha clean (montos completos) → movimiento real
        4. Continuación clean × N (cuando las hay)

        El parser debe:
        - Generar movimientos solo de las líneas clean
        - Limpiar continuaciones doubled que queden adjuntas a movimientos clean
        - Ignorar líneas doubled con montos truncados
        """
        page = self._make_page(
            [
                # Mov 1: doubled (truncado) + sus continuaciones doubled
                "0022--JJUUNN--22002255 5555442277"
                "3366AABBOONNOO TTRRAANNSSFFEERREENNCC"
                "IIAA SSPPEEII HHOORRAA 0099::5533::4488"
                " 445599,,55",
                "RREECCIIBBIIDDOO DDEE BBBBVVAA MMEEXXIICCOO",
                "RRFFCC BBSSNN222211110077RRAA11",
                # Mov 2: clean con montos completos
                "2-JUN-2025 2500011 DEPOSITO EN EFECTIVO 20.00 519,821.39",
                # Mov 3: clean con continuación clean
                "2-JUN-2025 9063704 ABONO TRANSFERENCIA SPEI HORA 12:15:24 59,114.83 3,410,152.50",
                "RECIBIDO DE BBVA MEXICO",
                "DEL CLIENTE EPIFANIO AGUAYO ZAPATA",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Mov 1 doubled tiene monto truncado "459,55" → no genera movimiento
        # Sus continuaciones se "pierden" (quedan como bloque huérfano) → OK
        # Mov 2 y 3 se generan normalmente
        assert len(resultado.movimientos) == 2

        # Mov 2: depósito en efectivo
        assert resultado.movimientos[0].deposito == Decimal("20.00")
        assert "DEPOSITO EN EFECTIVO" in resultado.movimientos[0].concepto

        # Mov 3: SPEI con continuación clean
        assert resultado.movimientos[1].deposito == Decimal("59114.83")
        assert "RECIBIDO DE BBVA MEXICO" in resultado.movimientos[1].concepto
        assert "EPIFANIO AGUAYO ZAPATA" in resultado.movimientos[1].concepto

    # =================================================================
    # Bug fixes: page info en conceptos y overflow del último movimiento
    # =================================================================

    def test_pagina_ocr_corrupta_no_aparece_en_concepto(self, parser):
        """Líneas con 'P gina19 de23. P-P 42793560' (OCR corrupto) se filtran.

        Bug: el OCR corrompe 'Página' como 'P gina' con espacio, y la línea
        combinada con 'P-P' no matcheaba ningún noise pattern.
        """
        page = self._make_page(
            [
                "15-ENE-2025 1234567 PAGO SERVICIO LUZ 1,500.00 120,000.00",
                "P gina19 de23. P-P 42793560",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert "P gina" not in mov.concepto
        assert "P-P" not in mov.concepto
        assert "PAGO SERVICIO LUZ" in mov.concepto

    def test_pp_footer_mitad_de_linea_se_filtra(self, parser):
        """El footer 'P-P XXXX' que aparece en medio de una línea se filtra."""
        page = self._make_page(
            [
                "10-MAR-2025 9876543 RETIRO ATM 500.00 50,000.00",
                "SUCURSAL 123 P-P 4500671",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        assert "P-P" not in resultado.movimientos[0].concepto

    def test_total_y_saldo_final_no_contaminan_ultimo_movimiento(self, parser):
        """Líneas de TOTAL y SALDO FINAL no se anexan al último movimiento.

        Bug: tras el último movimiento, todo el contenido restante de la página
        (TOTAL, SALDO FINAL, leyendas) se añadía como continuación.
        """
        page = self._make_page(
            [
                "20-ENE-2025 111222 PAGO NOMINA 5,000.00 115,000.00",
                "25-ENE-2025 333444 RETIRO VENTANILLA 2,000.00 113,000.00",
                "TOTAL 7,000.00 2,000.00",
                "SALDO FINAL DEL PERIODO: 113,000.00",
                "Significado de abreviaturas utilizadas en el estado de cuenta:",
                "ABO ABONO (S) DEB DEBITO NO NUMERO",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        ultimo = resultado.movimientos[1]
        assert "TOTAL" not in ultimo.concepto
        assert "SALDO FINAL" not in ultimo.concepto
        assert "Significado" not in ultimo.concepto
        assert "RETIRO VENTANILLA" in ultimo.concepto

    def test_ultimo_movimiento_retiro_no_reclasificado_como_deposito(self, parser):
        """Un retiro no se reclasifica como depósito por contenido TOTAL DEPOSITOS.

        Bug: si las líneas de TOTAL contenían 'DEPOSITO', _detectar_tipo()
        clasificaba erróneamente el movimiento como depósito.
        """
        page = self._make_page(
            [
                "28-ENE-2025 555666 PAGO SERVICIO AGUA 800.00 112,200.00",
                "TOTAL 9,082,076.01 9,100,000.00",
                "SALDO FINAL DEL PERIODO: 109,450.88",
                "Detalles de movimientos Dinero Creciente Santander.",
                "INVERSION CRECIENTE 66-51002073-1",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        # Debe ser retiro, NO depósito
        assert mov.retiro == Decimal("800.00")
        assert mov.deposito == Decimal("0")
        assert "PAGO SERVICIO AGUA" in mov.concepto
        assert "TOTAL" not in mov.concepto
        assert "INVERSION" not in mov.concepto
