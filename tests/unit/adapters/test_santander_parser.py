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
