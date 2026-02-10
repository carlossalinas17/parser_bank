# """
# Tests para el parser de Scotiabank.

# Diferencias clave que estos tests validan vs Santander:
# - Fecha "DD MMM" sin año (año extraído del encabezado).
# - Montos con signo $: $1,500.00.
# - Conceptos MULTI-LÍNEA (hasta 15 líneas por movimiento).
# - Sección de movimientos delimitada por marcadores.
# - Clasificación con PRIORIDAD: retiros se evalúan primero.
# - Caso especial: "SEL TRASPASO ENTRE CUENTAS" → retiro por default.
# - Referencia: 10+ dígitos dentro del concepto.
# """

# from datetime import date
# from decimal import Decimal

# import pytest

# from src.adapters.input.bank_parsers.scotiabank_parser import ScotiabankParser
# from src.domain.exceptions import ParseError
# from src.domain.models.page_text import PageText


# class TestScotiabankParser:
#     """Tests unitarios para ScotiabankParser."""

#     @pytest.fixture
#     def parser(self):
#         return ScotiabankParser()

#     # === Helpers ===

#     def _make_page(
#         self,
#         movimiento_lines: list[str] | None = None,
#         header: str | None = None,
#         include_section_marker: bool = True,
#     ) -> PageText:
#         """Crea una página simulada de Scotiabank.

#         Args:
#             movimiento_lines: Líneas de movimientos.
#             header: Texto del encabezado.
#             include_section_marker: Si True, agrega "Detalle de tus
#                 movimientos" antes de los movimientos.
#         """
#         if header is None:
#             header = (
#                 "Scotiabank Inverlat S.A.\n"
#                 "Estado de Cuenta\n"
#                 "Cuenta 00441580\n"
#                 "Periodo 01-NOV-25 al 30-NOV-25\n"
#                 "Moneda NACIONAL\n"
#             )

#         parts = [header]

#         if include_section_marker:
#             parts.append("Detalle de tus movimientos")

#         if movimiento_lines:
#             parts.extend(movimiento_lines)

#         text = "\n".join(parts)
#         return PageText(page_num=1, text=text)

#     # === Tests de retiros (default y por keywords) ===

#     def test_retiro_basico(self, parser):
#         """Una línea con concepto sin keyword de depósito → retiro."""
#         page = self._make_page(
#             [
#                 "15 NOV COMPRA TIENDA DEPTO $1,500.00 $118,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert len(resultado.movimientos) == 1
#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("1500.00")
#         assert mov.deposito == Decimal("0")
#         assert mov.tipo == "retiro"

#     def test_retiro_keyword_cargo(self, parser):
#         """Concepto con 'CARGO' → retiro."""
#         page = self._make_page(
#             [
#                 "10 NOV CARGO DOMICILIADO CFE $2,300.00 $116,200.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("2300.00")

#     def test_retiro_keyword_comision(self, parser):
#         """Concepto con 'COBRO DE COMISION' → retiro."""
#         page = self._make_page(
#             [
#                 "20 NOV COBRO DE COMISION MENSUAL $580.00 $117,920.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("580.00")

#     def test_retiro_keyword_operacion_mt101(self, parser):
#         """Concepto con 'OPERACION MT101' → retiro."""
#         page = self._make_page(
#             [
#                 "05 NOV OPERACION MT101 TRANSFERENCIA $50,000.00 $68,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("50000.00")

#     # === Tests de depósitos (por keywords) ===

#     def test_deposito_keyword_abono(self, parser):
#         """Concepto con 'ABONO' → depósito."""
#         page = self._make_page(
#             [
#                 "10 NOV ABONO TRANSFERENCIA $50,000.00 $170,000.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.deposito == Decimal("50000.00")
#         assert mov.retiro == Decimal("0")
#         assert mov.tipo == "deposito"

#     def test_deposito_keyword_deposito(self, parser):
#         """Concepto con 'DEPOSITO' → depósito."""
#         page = self._make_page(
#             [
#                 "05 NOV DEPOSITO EN EFECTIVO $30,000.00 $150,000.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.deposito == Decimal("30000.00")

#     def test_deposito_keyword_transferencia_recibida(self, parser):
#         """Concepto con 'TRANSFERENCIA RECIBIDA' → depósito."""
#         page = self._make_page(
#             [
#                 "07 NOV TRANSFERENCIA RECIBIDA SPEI $15,000.00 $135,000.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.deposito == Decimal("15000.00")

#     def test_deposito_keyword_spei(self, parser):
#         """'TRANSF INTERBANCARIA SPEI' → depósito (sin 'SEL' al inicio)."""
#         page = self._make_page(
#             [
#                 "12 NOV TRANSF INTERBANCARIA SPEI $75,000.00 $193,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.deposito == Decimal("75000.00")

#     # === Test prioridad de keywords ===

#     def test_prioridad_retiro_sobre_deposito(self, parser):
#         """'SEL TRANSF. INTERBANCARIA SPEI' es retiro (prioridad sobre
#         'TRANSF INTERBANCARIA SPEI' que sería depósito)."""
#         page = self._make_page(
#             [
#                 "15 NOV SEL TRANSF. INTERBANCARIA SPEI $25,000.00 $93,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("25000.00")
#         assert mov.tipo == "retiro"

#     # === Test caso especial: traspaso entre cuentas ===

#     def test_traspaso_entre_cuentas_default_retiro(self, parser):
#         """'SEL TRASPASO ENTRE CUENTAS' → retiro por default."""
#         page = self._make_page(
#             [
#                 "18 NOV SEL TRASPASO ENTRE CUENTAS 00000000000000000018 $10,000.00 $108,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("10000.00")
#         assert mov.tipo == "retiro"

#     # === Tests de conceptos multi-línea ===

#     def test_concepto_multilinea(self, parser):
#         """Un movimiento cuyo concepto abarca 2 líneas."""
#         page = self._make_page(
#             [
#                 "15 NOV COBRO DE COMISION POR MANEJO",
#                 "DE CUENTA EMPRESARIAL $580.00 $117,920.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert len(resultado.movimientos) == 1
#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("580.00")
#         assert "COMISION" in mov.concepto
#         assert "EMPRESARIAL" in mov.concepto

#     def test_concepto_multilinea_con_referencia(self, parser):
#         """Concepto multi-línea con referencia en línea separada."""
#         page = self._make_page(
#             [
#                 "08 NOV CARGO DOMICILIADO",
#                 "REF 1234567890123 CFE $2,100.00 $115,400.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert mov.retiro == Decimal("2100.00")
#         assert mov.referencia == "1234567890123"

#     def test_dos_movimientos_consecutivos(self, parser):
#         """Dos movimientos consecutivos se separan por la fecha."""
#         page = self._make_page(
#             [
#                 "10 NOV PAGO SERVICIO LUZ $1,500.00 $118,500.00",
#                 "12 NOV DEPOSITO EFECTIVO $5,000.00 $123,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert len(resultado.movimientos) == 2
#         assert resultado.movimientos[0].retiro == Decimal("1500.00")
#         assert resultado.movimientos[1].deposito == Decimal("5000.00")

#     # === Tests de sección de movimientos ===

#     def test_ignora_lineas_antes_de_seccion(self, parser):
#         """Líneas antes de 'Detalle de tus movimientos' se ignoran."""
#         page = self._make_page(
#             movimiento_lines=[
#                 "15 NOV PAGO SERVICIO $1,500.00 $118,500.00",
#             ],
#             include_section_marker=True,
#         )
#         # El encabezado tiene datos numéricos pero no son movimientos
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert len(resultado.movimientos) == 1

#     def test_sin_seccion_movimientos_no_extrae(self, parser):
#         """Si no hay marcador de sección, no extrae movimientos."""
#         page = self._make_page(
#             movimiento_lines=[
#                 "15 NOV PAGO SERVICIO $1,500.00 $118,500.00",
#             ],
#             include_section_marker=False,
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert len(resultado.movimientos) == 0

#     def test_ignora_encabezados_repetidos(self, parser):
#         """Líneas como 'Fecha Concepto Origen' se ignoran."""
#         page = self._make_page(
#             [
#                 "15 NOV PAGO LUZ $1,500.00 $118,500.00",
#                 "Fecha Concepto Origen",
#                 "20 NOV DEPOSITO $5,000.00 $123,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert len(resultado.movimientos) == 2

#     # === Tests de info de cuenta ===

#     def test_extrae_cuenta(self, parser):
#         page = self._make_page()
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.info_cuenta.banco == "SCOTIABANK"
#         assert resultado.info_cuenta.cuenta == "00441580"
#         assert resultado.info_cuenta.moneda == "MXN"

#     def test_moneda_usd(self, parser):
#         page = self._make_page(
#             header=(
#                 "Scotiabank Inverlat\n"
#                 "Cuenta 00441580\n"
#                 "Periodo 01-NOV-25 al 30-NOV-25\n"
#                 "Moneda DOLARES USD\n"
#             ),
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.info_cuenta.moneda == "USD"

#     def test_cuenta_no_encontrada(self, parser):
#         page = self._make_page(
#             header=("Scotiabank Inverlat\n" "Periodo 01-NOV-25 al 30-NOV-25\n"),
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.info_cuenta.cuenta == "SIN_CUENTA"

#     # === Tests de periodo ===

#     def test_extrae_periodo(self, parser):
#         page = self._make_page()
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.año == 2025
#         assert resultado.mes == 11

#     def test_periodo_usa_ultima_fecha(self, parser):
#         """Si hay dos fechas DD-MMM-YY, usa la última (fecha de corte)."""
#         page = self._make_page(
#             header=("Scotiabank Inverlat\n" "Cuenta 00441580\n" "Periodo 01-OCT-25 al 31-OCT-25\n"),
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         # Toma la última: 31-OCT-25 → octubre
#         assert resultado.año == 2025
#         assert resultado.mes == 10

#     # === Tests de fechas ===

#     def test_fecha_sin_año_usa_año_encabezado(self, parser):
#         """La fecha 'DD MMM' usa el año extraído del encabezado."""
#         page = self._make_page(
#             [
#                 "03 NOV PAGO SERVICIO $800.00 $119,200.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.movimientos[0].fecha == date(2025, 11, 3)

#     def test_fecha_mes_ingles(self, parser):
#         """Scotiabank a veces usa abreviaciones en inglés (JAN, APR)."""
#         page = self._make_page(
#             header=("Scotiabank Inverlat\n" "Cuenta 00441580\n" "Periodo 01-JAN-25 al 31-JAN-25\n"),
#             movimiento_lines=[
#                 "15 JAN PAGO SERVICIO $800.00 $119,200.00",
#             ],
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.movimientos[0].fecha == date(2025, 1, 15)

#     # === Tests de referencia ===

#     def test_extrae_referencia_10_digitos(self, parser):
#         """Números de 10+ dígitos en el concepto → referencia."""
#         page = self._make_page(
#             [
#                 "15 NOV PAGO SERVICIO 1234567890 $1,500.00 $118,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.movimientos[0].referencia == "1234567890"

#     def test_sin_referencia(self, parser):
#         """Sin números largos → referencia vacía."""
#         page = self._make_page(
#             [
#                 "15 NOV PAGO LUZ $1,500.00 $118,500.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.movimientos[0].referencia == ""

#     # === Tests de resumen ===

#     def test_calcula_resumen(self, parser):
#         page = self._make_page(
#             [
#                 "01 NOV DEPOSITO EFECTIVO $10,000.00 $130,000.00",
#                 "05 NOV PAGO LUZ $2,000.00 $128,000.00",
#                 "10 NOV ABONO TRANSFER $5,000.00 $133,000.00",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert resultado.resumen.total_depositos == Decimal("15000.00")
#         assert resultado.resumen.total_retiros == Decimal("2000.00")
#         assert resultado.resumen.num_depositos == 2
#         assert resultado.resumen.num_retiros == 1

#     # === Tests de Decimal ===

#     def test_montos_usan_decimal(self, parser):
#         page = self._make_page(
#             [
#                 "15 NOV PAGO $1,234.56 $118,765.44",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         mov = resultado.movimientos[0]
#         assert isinstance(mov.retiro, Decimal)

#     # === Tests de líneas ignoradas ===

#     def test_ignora_linea_sin_monto(self, parser):
#         """Líneas con fecha pero sin montos se ignoran."""
#         page = self._make_page(
#             [
#                 "15 NOV SALDO ANTERIOR",
#             ]
#         )
#         resultado = parser.parse([page], file_name="test.pdf")

#         assert len(resultado.movimientos) == 0

#     # === Tests de errores ===

#     def test_error_sin_paginas(self, parser):
#         with pytest.raises(ParseError, match="No se recibieron"):
#             parser.parse([], file_name="test.pdf")

#     def test_bank_name(self, parser):
#         assert parser.bank_name == "SCOTIABANK"

#     # === Test no requiere words ===

#     def test_funciona_sin_words(self, parser):
#         """Scotiabank NO requiere coordenadas (como Santander)."""
#         page = PageText(
#             page_num=1,
#             text=(
#                 "Scotiabank\nCuenta 00441580\n"
#                 "Periodo 01-NOV-25 al 30-NOV-25\n"
#                 "Detalle de tus movimientos\n"
#                 "15 NOV PAGO SERVICIO $1,500.00 $118,500.00"
#             ),
#         )
#         assert not page.has_words

#         resultado = parser.parse([page], file_name="test.pdf")
#         assert len(resultado.movimientos) == 1


"""
Tests para el parser de Scotiabank - Versión actualizada para incluir toda la información.

Diferencias clave que estos tests validan:
- Fecha "DD MMM" sin año (año extraído del encabezado).
- Montos con signo $: $1,500.00.
- Conceptos MULTI-LÍNEA incluyendo toda la información de "Origen/Referencia".
- Sección de movimientos delimitada por marcadores.
- Clasificación con PRIORIDAD: retiros se evalúan primero.
- Caso especial: "SEL TRASPASO ENTRE CUENTAS" → retiro por default.
- Referencia: 10+ dígitos dentro del concepto.
- Captura COMPLETA de todas las líneas del movimiento.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.adapters.input.bank_parsers.scotiabank_parser import ScotiabankParser
from src.domain.exceptions import ParseError
from src.domain.models.page_text import PageText


class TestScotiabankParser:
    """Tests unitarios actualizados para ScotiabankParser."""

    @pytest.fixture
    def parser(self):
        return ScotiabankParser()

    # === Helpers ===

    def _make_page(
        self,
        movimiento_lines: list[str] | None = None,
        header: str | None = None,
        include_section_marker: bool = True,
    ) -> PageText:
        """Crea una página simulada de Scotiabank.

        Args:
            movimiento_lines: Líneas de movimientos.
            header: Texto del encabezado.
            include_section_marker: Si True, agrega "Detalle de tus
                movimientos" antes de los movimientos.
        """
        if header is None:
            header = (
                "Scotiabank Inverlat S.A.\n"
                "Estado de Cuenta\n"
                "Cuenta 00441580\n"
                "Periodo 01-NOV-25 al 30-NOV-25\n"
                "Moneda NACIONAL\n"
            )

        parts = [header]

        if include_section_marker:
            parts.append("Detalle de tus movimientos")

        if movimiento_lines:
            parts.extend(movimiento_lines)

        text = "\n".join(parts)
        return PageText(page_num=1, text=text)

    # === Tests para verificar captura completa de información ===

    def test_concepto_con_origen_referencia_completo(self, parser):
        """Verifica que se capture TODO el concepto incluyendo origen/referencia."""
        page = self._make_page(
            [
                "30 ABR COBRO DE COMISION",
                "SCOTIA EN LINEA",
                "ANUALIDAD",
                "NUM OP 000000001",
                "00000000000000000182621433",
                "300425",
                "FORMA DE PAGO 03 $3,500.00 $2,638,272.67",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]

        # Verificar monto
        assert mov.retiro == Decimal("3500.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

        # Verificar que el concepto incluya TODAS las líneas
        concepto = mov.concepto
        assert "COBRO DE COMISION" in concepto
        assert "SCOTIA EN LINEA" in concepto
        assert "ANUALIDAD" in concepto
        assert "NUM OP 000000001" in concepto
        assert "00000000000000000182621433" in concepto
        assert "300425" in concepto
        assert "FORMA DE PAGO 03" in concepto

        # Verificar que los montos NO estén en el concepto
        assert "$3,500.00" not in concepto
        assert "$2,638,272.67" not in concepto

        # Verificar referencia
        assert mov.referencia == "00000000000000000182621433"

    def test_movimiento_con_iva_y_referencia(self, parser):
        """Test con IVA y referencia incluidos en el concepto."""
        page = self._make_page(
            [
                "30 ABR IVA POR COMISIONES",
                "SCOTIA EN LINEA",
                "ANUALIDAD",
                "NUM OP 000000001",
                "00000000000000000182621433",
                "300425",
                "FORMA DE PAGO 03 16.00% $560.00 $2,637,712.67",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]

        # Verificar monto del IVA
        assert mov.retiro == Decimal("560.00")
        assert mov.tipo == "retiro"

        # Verificar contenido completo
        concepto = mov.concepto
        assert "IVA POR COMISIONES" in concepto
        assert "SCOTIA EN LINEA" in concepto
        assert "ANUALIDAD" in concepto
        assert "16.00%" in concepto  # El porcentaje debe quedar
        assert "NUM OP 000000001" in concepto
        assert "FORMA DE PAGO 03" in concepto

        # Verificar que los montos NO estén
        assert "$560.00" not in concepto
        assert "$2,637,712.67" not in concepto

    def test_concepto_multilinea_con_abreviaturas(self, parser):
        """Test con abreviaturas y múltiples líneas."""
        page = self._make_page(
            [
                "15 NOV TRANSF INTERBANCARIA SPEI",
                "BENEFICIARIO: JUAN PEREZ",
                "CLABE: 012180000000000123",
                "CONCEPTO: PAGO SERVICIO",
                "REF: 20231115001 $15,000.00 $150,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        concepto = mov.concepto

        # Verificar que toda la información está incluida
        assert "TRANSF INTERBANCARIA SPEI" in concepto
        assert "BENEFICIARIO: JUAN PEREZ" in concepto
        assert "CLABE: 012180000000000123" in concepto
        assert "CONCEPTO: PAGO SERVICIO" in concepto
        assert "REF: 20231115001" in concepto

        # Verificar que los montos NO estén
        assert "$15,000.00" not in concepto
        assert "$150,000.00" not in concepto

        # Verificar tipo (debe ser depósito por TRANSF INTERBANCARIA SPEI sin SEL)
        assert mov.deposito == Decimal("15000.00")
        assert mov.tipo == "deposito"

        # Verificar referencia
        assert mov.referencia == "012180000000000123"

    def test_dos_movimientos_completos_consecutivos(self, parser):
        """Dos movimientos completos con toda su información."""
        page = self._make_page(
            [
                "10 NOV COBRO DE COMISION MENSUAL",
                "REF 1234567890123 $580.00 $117,920.00",
                "12 NOV DEPOSITO EN EFECTIVO",
                "VENTA PRODUCTOS",
                "REF CAJA 001 $5,000.00 $122,920.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2

        # Primer movimiento (retiro)
        mov1 = resultado.movimientos[0]
        assert mov1.fecha == date(2025, 11, 10)
        assert mov1.retiro == Decimal("580.00")
        assert mov1.deposito == Decimal("0")
        assert mov1.tipo == "retiro"
        assert "COBRO DE COMISION MENSUAL" in mov1.concepto
        assert "REF 1234567890123" in mov1.concepto
        assert "$580.00" not in mov1.concepto
        assert "$117,920.00" not in mov1.concepto
        assert mov1.referencia == "1234567890123"

        # Segundo movimiento (depósito)
        mov2 = resultado.movimientos[1]
        assert mov2.fecha == date(2025, 11, 12)
        assert mov2.deposito == Decimal("5000.00")
        assert mov2.retiro == Decimal("0")
        assert mov2.tipo == "deposito"
        assert "DEPOSITO EN EFECTIVO" in mov2.concepto
        assert "VENTA PRODUCTOS" in mov2.concepto
        assert "REF CAJA 001" in mov2.concepto
        assert "$5,000.00" not in mov2.concepto
        assert "$122,920.00" not in mov2.concepto

    def test_concepto_con_numeros_operacion_y_fecha(self, parser):
        """Concepto con números de operación y fechas en referencia."""
        page = self._make_page(
            [
                "25 NOV SEL TRANSF. INTERBANCARIA SPEI",
                "BENEF: MARIA GARCIA",
                "OP 7890123456 FECHA 251125",
                "CONCEPTO TRASPASO $25,000.00 $93,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        concepto = mov.concepto

        # Verificar toda la información está incluida
        assert "SEL TRANSF. INTERBANCARIA SPEI" in concepto
        assert "BENEF: MARIA GARCIA" in concepto
        assert "OP 7890123456" in concepto
        assert "FECHA 251125" in concepto
        assert "CONCEPTO TRASPASO" in concepto

        # Verificar que los montos NO estén
        assert "$25,000.00" not in concepto
        assert "$93,500.00" not in concepto

        # Verificar tipo (SEL TRANSF... es retiro)
        assert mov.retiro == Decimal("25000.00")
        assert mov.tipo == "retiro"

    # === Tests de retiros (default y por keywords) ===

    def test_retiro_basico(self, parser):
        """Una línea con concepto sin keyword de depósito → retiro."""
        page = self._make_page(
            [
                "15 NOV COMPRA TIENDA DEPTO $1,500.00 $118,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("1500.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

    def test_retiro_keyword_cargo(self, parser):
        """Concepto con 'CARGO' → retiro."""
        page = self._make_page(
            [
                "10 NOV CARGO DOMICILIADO CFE $2,300.00 $116,200.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("2300.00")
        assert mov.tipo == "retiro"

    def test_retiro_keyword_comision(self, parser):
        """Concepto con 'COBRO DE COMISION' → retiro."""
        page = self._make_page(
            [
                "20 NOV COBRO DE COMISION MENSUAL $580.00 $117,920.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("580.00")
        assert mov.tipo == "retiro"

    def test_retiro_keyword_operacion_mt101(self, parser):
        """Concepto con 'OPERACION MT101' → retiro."""
        page = self._make_page(
            [
                "05 NOV OPERACION MT101 TRANSFERENCIA $50,000.00 $68,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("50000.00")
        assert mov.tipo == "retiro"

    # === Tests de depósitos (por keywords) ===

    def test_deposito_keyword_abono(self, parser):
        """Concepto con 'ABONO' → depósito."""
        page = self._make_page(
            [
                "10 NOV ABONO TRANSFERENCIA $50,000.00 $170,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("50000.00")
        assert mov.retiro == Decimal("0")
        assert mov.tipo == "deposito"

    def test_deposito_keyword_deposito(self, parser):
        """Concepto con 'DEPOSITO' → depósito."""
        page = self._make_page(
            [
                "05 NOV DEPOSITO EN EFECTIVO $30,000.00 $150,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("30000.00")
        assert mov.tipo == "deposito"

    def test_deposito_keyword_transferencia_recibida(self, parser):
        """Concepto con 'TRANSFERENCIA RECIBIDA' → depósito."""
        page = self._make_page(
            [
                "07 NOV TRANSFERENCIA RECIBIDA SPEI $15,000.00 $135,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("15000.00")
        assert mov.tipo == "deposito"

    def test_deposito_keyword_spei(self, parser):
        """'TRANSF INTERBANCARIA SPEI' → depósito (sin 'SEL' al inicio)."""
        page = self._make_page(
            [
                "12 NOV TRANSF INTERBANCARIA SPEI $75,000.00 $193,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.deposito == Decimal("75000.00")
        assert mov.tipo == "deposito"

    # === Test prioridad de keywords ===

    def test_prioridad_retiro_sobre_deposito(self, parser):
        """'SEL TRANSF. INTERBANCARIA SPEI' es retiro (prioridad sobre
        'TRANSF INTERBANCARIA SPEI' que sería depósito)."""
        page = self._make_page(
            [
                "15 NOV SEL TRANSF. INTERBANCARIA SPEI $25,000.00 $93,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("25000.00")
        assert mov.deposito == Decimal("0")
        assert mov.tipo == "retiro"

    # === Test caso especial: traspaso entre cuentas ===

    def test_traspaso_entre_cuentas_default_retiro(self, parser):
        """'SEL TRASPASO ENTRE CUENTAS' → retiro por default."""
        page = self._make_page(
            [
                "18 NOV SEL TRASPASO ENTRE CUENTAS 00000000000000000018 $10,000.00 $108,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("10000.00")
        assert mov.tipo == "retiro"

    # === Tests de conceptos multi-línea (mantenidos para compatibilidad) ===

    def test_concepto_multilinea(self, parser):
        """Un movimiento cuyo concepto abarca 2 líneas."""
        page = self._make_page(
            [
                "15 NOV COBRO DE COMISION POR MANEJO",
                "DE CUENTA EMPRESARIAL $580.00 $117,920.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("580.00")
        assert mov.tipo == "retiro"
        assert "COBRO DE COMISION POR MANEJO" in mov.concepto
        assert "DE CUENTA EMPRESARIAL" in mov.concepto
        assert "$580.00" not in mov.concepto
        assert "$117,920.00" not in mov.concepto

    def test_concepto_multilinea_con_referencia(self, parser):
        """Concepto multi-línea con referencia en línea separada."""
        page = self._make_page(
            [
                "08 NOV CARGO DOMICILIADO",
                "REF 1234567890123 CFE $2,100.00 $115,400.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert mov.retiro == Decimal("2100.00")
        assert mov.tipo == "retiro"
        assert mov.referencia == "1234567890123"
        assert "CARGO DOMICILIADO" in mov.concepto
        assert "REF 1234567890123 CFE" in mov.concepto

    def test_dos_movimientos_consecutivos(self, parser):
        """Dos movimientos consecutivos se separan por la fecha."""
        page = self._make_page(
            [
                "10 NOV PAGO SERVICIO LUZ $1,500.00 $118,500.00",
                "12 NOV DEPOSITO EFECTIVO $5,000.00 $123,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2
        assert resultado.movimientos[0].retiro == Decimal("1500.00")
        assert resultado.movimientos[0].tipo == "retiro"
        assert resultado.movimientos[1].deposito == Decimal("5000.00")
        assert resultado.movimientos[1].tipo == "deposito"

    # === Tests de sección de movimientos ===

    def test_ignora_lineas_antes_de_seccion(self, parser):
        """Líneas antes de 'Detalle de tus movimientos' se ignoran."""
        page = self._make_page(
            movimiento_lines=[
                "15 NOV PAGO SERVICIO $1,500.00 $118,500.00",
            ],
            include_section_marker=True,
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1

    def test_sin_seccion_movimientos_no_extrae(self, parser):
        """Si no hay marcador de sección, no extrae movimientos."""
        page = self._make_page(
            movimiento_lines=[
                "15 NOV PAGO SERVICIO $1,500.00 $118,500.00",
            ],
            include_section_marker=False,
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 0

    def test_ignora_encabezados_repetidos(self, parser):
        """Líneas como 'Fecha Concepto Origen' se ignoran."""
        page = self._make_page(
            [
                "15 NOV PAGO LUZ $1,500.00 $118,500.00",
                "Fecha Concepto Origen",
                "20 NOV DEPOSITO $5,000.00 $123,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2

    # === Tests de info de cuenta ===

    def test_extrae_cuenta(self, parser):
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.banco == "SCOTIABANK"
        assert resultado.info_cuenta.cuenta == "00441580"
        assert resultado.info_cuenta.moneda == "MXN"

    def test_moneda_usd(self, parser):
        page = self._make_page(
            header=(
                "Scotiabank Inverlat\n"
                "Cuenta 00441580\n"
                "Periodo 01-NOV-25 al 30-NOV-25\n"
                "Moneda DOLARES USD\n"
            ),
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.moneda == "USD"

    def test_cuenta_no_encontrada(self, parser):
        page = self._make_page(
            header=("Scotiabank Inverlat\n" "Periodo 01-NOV-25 al 30-NOV-25\n"),
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.info_cuenta.cuenta == "SIN_CUENTA"

    # === Tests de periodo ===

    def test_extrae_periodo(self, parser):
        page = self._make_page()
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.año == 2025
        assert resultado.mes == 11

    def test_periodo_usa_ultima_fecha(self, parser):
        """Si hay dos fechas DD-MMM-YY, usa la última (fecha de corte)."""
        page = self._make_page(
            header=("Scotiabank Inverlat\n" "Cuenta 00441580\n" "Periodo 01-OCT-25 al 31-OCT-25\n"),
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # Toma la última: 31-OCT-25 → octubre
        assert resultado.año == 2025
        assert resultado.mes == 10

    # === Tests de fechas ===

    def test_fecha_sin_año_usa_año_encabezado(self, parser):
        """La fecha 'DD MMM' usa el año extraído del encabezado."""
        page = self._make_page(
            [
                "03 NOV PAGO SERVICIO $800.00 $119,200.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2025, 11, 3)

    def test_fecha_mes_ingles(self, parser):
        """Scotiabank a veces usa abreviaciones en inglés (JAN, APR)."""
        page = self._make_page(
            header=("Scotiabank Inverlat\n" "Cuenta 00441580\n" "Periodo 01-JAN-25 al 31-JAN-25\n"),
            movimiento_lines=[
                "15 JAN PAGO SERVICIO $800.00 $119,200.00",
            ],
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].fecha == date(2025, 1, 15)

    # === Tests de referencia ===

    def test_extrae_referencia_10_digitos(self, parser):
        """Números de 10+ dígitos en el concepto → referencia."""
        page = self._make_page(
            [
                "15 NOV PAGO SERVICIO 1234567890 $1,500.00 $118,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].referencia == "1234567890"

    def test_sin_referencia(self, parser):
        """Sin números largos → referencia vacía."""
        page = self._make_page(
            [
                "15 NOV PAGO LUZ $1,500.00 $118,500.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.movimientos[0].referencia == ""

    # === Tests de resumen ===

    def test_calcula_resumen(self, parser):
        page = self._make_page(
            [
                "01 NOV DEPOSITO EFECTIVO $10,000.00 $130,000.00",
                "05 NOV PAGO LUZ $2,000.00 $128,000.00",
                "10 NOV ABONO TRANSFER $5,000.00 $133,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert resultado.resumen.total_depositos == Decimal("15000.00")
        assert resultado.resumen.total_retiros == Decimal("2000.00")
        assert resultado.resumen.num_depositos == 2
        assert resultado.resumen.num_retiros == 1

    # === Tests de Decimal ===

    def test_montos_usan_decimal(self, parser):
        page = self._make_page(
            [
                "15 NOV PAGO $1,234.56 $118,765.44",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        assert isinstance(mov.retiro, Decimal)

    # === Tests de líneas ignoradas ===

    def test_ignora_linea_sin_monto(self, parser):
        """Líneas con fecha pero sin montos se ignoran."""
        page = self._make_page(
            [
                "15 NOV SALDO ANTERIOR",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 0

    # === Tests de límites y casos borde ===

    def test_concepto_muy_largo(self, parser):
        """Concepto que alcanza el límite máximo de líneas."""
        lineas_largas = [f"Línea de descripción {i}" for i in range(parser._MAX_CONCEPT_LINES)]
        lineas_largas[0] = "15 NOV PAGO SERVICIO"
        lineas_largas[-1] = lineas_largas[-1] + " $1,500.00 $118,500.00"

        page = self._make_page(lineas_largas)
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 1
        mov = resultado.movimientos[0]

        # Verificar que se capturó la mayor cantidad posible
        assert len(mov.concepto) > 100  # Debe ser largo
        assert "$1,500.00" not in mov.concepto

    def test_movimiento_sin_montos_suficientes(self, parser):
        """Línea con fecha pero sin 2 montos (solo saldo anterior)."""
        page = self._make_page(
            [
                "01 NOV SALDO ANTERIOR $100,000.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        # No debería crear movimiento porque falta el monto de operación
        assert len(resultado.movimientos) == 0

    def test_concepto_con_porcentajes_y_numeros(self, parser):
        """Concepto que incluye porcentajes y números varios."""
        page = self._make_page(
            [
                "20 NOV IVA - COMISIONES",
                "TASA 16.00% BASE $3,500.00",
                "REF COM20231120 $560.00 $117,360.00",
            ]
        )
        resultado = parser.parse([page], file_name="test.pdf")

        mov = resultado.movimientos[0]
        concepto = mov.concepto

        # Verificar que se mantienen porcentajes y números no monetarios
        assert "IVA - COMISIONES" in concepto
        assert "TASA 16.00%" in concepto
        assert "BASE" in concepto
        # El monto $3,500.00 debería limpiarse pero "BASE" debe quedar
        assert "BASE $3,500.00" not in concepto
        assert "REF COM20231120" in concepto
        assert mov.referencia == "20231120"  # Solo los 8+ dígitos

    # === Test de integración con ejemplo real ===

    def test_ejemplo_real_desde_pdf(self, parser):
        """Test con el ejemplo real del PDF proporcionado."""
        page = PageText(
            page_num=1,
            text=(
                "Scotiabank Inverlat S.A.\n"
                "Estado de Cuenta\n"
                "Cuenta 04804643003\n"
                "Periodo 01-ABR-25 al 30-ABR-25\n"
                "Moneda NACIONAL\n"
                "Detalle de tus movimientos\n"
                "30 ABR COBRO DE COMISION\n"
                "SCOTIA EN LINEA\n"
                "ANUALIDAD\n"
                "NUM OP 000000001\n"
                "00000000000000000182621433\n"
                "300425\n"
                "FORMA DE PAGO 03 $3,500.00 $2,638,272.67\n"
                "30 ABR IVA POR COMISIONES\n"
                "SCOTIA EN LINEA\n"
                "ANUALIDAD\n"
                "NUM OP 000000001\n"
                "00000000000000000182621433\n"
                "300425\n"
                "FORMA DE PAGO 03 16.00% $560.00 $2,637,712.67"
            ),
        )
        resultado = parser.parse([page], file_name="test.pdf")

        assert len(resultado.movimientos) == 2

        # Primer movimiento: COBRO DE COMISION
        mov1 = resultado.movimientos[0]
        assert mov1.fecha == date(2025, 4, 30)
        assert mov1.retiro == Decimal("3500.00")
        assert mov1.deposito == Decimal("0")
        assert mov1.tipo == "retiro"
        assert "COBRO DE COMISION" in mov1.concepto
        assert "SCOTIA EN LINEA" in mov1.concepto
        assert "ANUALIDAD" in mov1.concepto
        assert "NUM OP 000000001" in mov1.concepto
        assert "00000000000000000182621433" in mov1.concepto
        assert "300425" in mov1.concepto
        assert "FORMA DE PAGO 03" in mov1.concepto
        assert "$3,500.00" not in mov1.concepto
        assert "$2,638,272.67" not in mov1.concepto
        assert mov1.referencia == "00000000000000000182621433"

        # Segundo movimiento: IVA POR COMISIONES
        mov2 = resultado.movimientos[1]
        assert mov2.fecha == date(2025, 4, 30)
        assert mov2.retiro == Decimal("560.00")
        assert mov2.deposito == Decimal("0")
        assert mov2.tipo == "retiro"
        assert "IVA POR COMISIONES" in mov2.concepto
        assert "16.00%" in mov2.concepto  # El porcentaje debe mantenerse
        assert "FORMA DE PAGO 03" in mov2.concepto
        assert "$560.00" not in mov2.concepto
        assert "$2,637,712.67" not in mov2.concepto
        assert mov2.referencia == "00000000000000000182621433"

    # === Tests de errores ===

    def test_error_sin_paginas(self, parser):
        with pytest.raises(ParseError, match="No se recibieron"):
            parser.parse([], file_name="test.pdf")

    def test_bank_name(self, parser):
        assert parser.bank_name == "SCOTIABANK"

    # === Test no requiere words ===

    def test_funciona_sin_words(self, parser):
        """Scotiabank NO requiere coordenadas (como Santander)."""
        page = PageText(
            page_num=1,
            text=(
                "Scotiabank\nCuenta 00441580\n"
                "Periodo 01-NOV-25 al 30-NOV-25\n"
                "Detalle de tus movimientos\n"
                "15 NOV PAGO SERVICIO $1,500.00 $118,500.00"
            ),
        )
        assert not page.has_words

        resultado = parser.parse([page], file_name="test.pdf")
        assert len(resultado.movimientos) == 1
        assert resultado.movimientos[0].retiro == Decimal("1500.00")
