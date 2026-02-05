"""
Tests para los modelos de dominio.

Verifican que las validaciones, propiedades derivadas e inmutabilidad
funcionan correctamente. Estos tests son la "especificación ejecutable"
del modelo de datos.
"""

from datetime import date
from decimal import Decimal

import pytest

from src.domain.models import (
    InfoCuenta,
    Movimiento,
    PageText,
    ResultadoParseo,
    Resumen,
)


class TestMovimiento:
    """Pruebas para el modelo Movimiento."""

    def test_crear_deposito(self):
        mov = Movimiento(
            fecha=date(2024, 10, 5),
            concepto="PAGO NOMINA",
            referencia="REF123",
            retiro=Decimal("0"),
            deposito=Decimal("50000.00"),
        )
        assert mov.tipo == "deposito"
        assert mov.monto == Decimal("50000.00")

    def test_crear_retiro(self):
        mov = Movimiento(
            fecha=date(2024, 10, 5),
            concepto="PAGO PROVEEDOR",
            referencia="REF456",
            retiro=Decimal("15000.00"),
            deposito=Decimal("0"),
        )
        assert mov.tipo == "retiro"
        assert mov.monto == Decimal("15000.00")

    def test_retiro_negativo_lanza_error(self):
        with pytest.raises(ValueError, match="negativo"):
            Movimiento(
                fecha=date(2024, 1, 1),
                concepto="X",
                referencia="",
                retiro=Decimal("-100"),
                deposito=Decimal("0"),
            )

    def test_deposito_negativo_lanza_error(self):
        with pytest.raises(ValueError, match="negativo"):
            Movimiento(
                fecha=date(2024, 1, 1),
                concepto="X",
                referencia="",
                retiro=Decimal("0"),
                deposito=Decimal("-100"),
            )

    def test_ambos_con_valor_lanza_error(self):
        """Un movimiento no puede ser retiro y depósito a la vez."""
        with pytest.raises(ValueError, match="al mismo tiempo"):
            Movimiento(
                fecha=date(2024, 1, 1),
                concepto="X",
                referencia="",
                retiro=Decimal("100"),
                deposito=Decimal("200"),
            )

    def test_ambos_en_cero_es_deposito(self):
        """Edge case: si ambos son 0, tipo es 'deposito' por defecto."""
        mov = Movimiento(
            fecha=date(2024, 1, 1),
            concepto="MOVIMIENTO SIN MONTO",
            referencia="",
            retiro=Decimal("0"),
            deposito=Decimal("0"),
        )
        assert mov.tipo == "deposito"
        assert mov.monto == Decimal("0")

    def test_es_inmutable(self):
        """frozen=True impide modificar después de crear."""
        mov = Movimiento(
            fecha=date(2024, 1, 1),
            concepto="X",
            referencia="",
            retiro=Decimal("0"),
            deposito=Decimal("100"),
        )
        with pytest.raises(AttributeError):
            mov.concepto = "MODIFICADO"  # type: ignore


class TestInfoCuenta:
    """Pruebas para el modelo InfoCuenta."""

    def test_crear_basico(self):
        info = InfoCuenta(banco="BBVA", cuenta="0123456789", moneda="MXN")
        assert info.banco == "BBVA"
        assert info.rfc == ""
        assert info.clabe == ""

    def test_crear_con_rfc_y_clabe(self):
        info = InfoCuenta(
            banco="MONEX",
            cuenta="12345678901234567",
            moneda="MXN",
            rfc="ABC123456AB1",
            clabe="012345678901234567",
        )
        assert info.rfc == "ABC123456AB1"

    def test_banco_vacio_lanza_error(self):
        with pytest.raises(ValueError, match="banco"):
            InfoCuenta(banco="", cuenta="123", moneda="MXN")

    def test_cuenta_vacia_lanza_error(self):
        with pytest.raises(ValueError, match="cuenta"):
            InfoCuenta(banco="BBVA", cuenta="", moneda="MXN")

    def test_moneda_invalida_lanza_error(self):
        with pytest.raises(ValueError, match="Moneda no reconocida"):
            InfoCuenta(banco="BBVA", cuenta="123", moneda="GBP")

    def test_monedas_validas(self):
        """MXN, USD y EUR son las monedas soportadas."""
        for moneda in ("MXN", "USD", "EUR"):
            info = InfoCuenta(banco="X", cuenta="123", moneda=moneda)
            assert info.moneda == moneda


class TestResumen:
    """Pruebas para el modelo Resumen."""

    def test_balance_movimientos(self):
        resumen = Resumen(
            total_depositos=Decimal("100000"),
            total_retiros=Decimal("30000"),
            num_depositos=5,
            num_retiros=3,
        )
        assert resumen.balance_movimientos == Decimal("70000")

    def test_diferencia_saldos_con_ambos(self):
        resumen = Resumen(
            total_depositos=Decimal("100000"),
            total_retiros=Decimal("30000"),
            num_depositos=5,
            num_retiros=3,
            saldo_inicial=Decimal("50000"),
            saldo_final=Decimal("120000"),
        )
        assert resumen.diferencia_saldos == Decimal("70000")

    def test_diferencia_saldos_sin_datos(self):
        resumen = Resumen(
            total_depositos=Decimal("100000"),
            total_retiros=Decimal("30000"),
            num_depositos=5,
            num_retiros=3,
        )
        assert resumen.diferencia_saldos is None


class TestPageText:
    """Pruebas para el modelo PageText."""

    def test_crear_pagina(self):
        page = PageText(page_num=1, text="Contenido de la página")
        assert page.page_num == 1

    def test_is_empty_con_texto(self):
        page = PageText(page_num=1, text="Contenido")
        assert page.is_empty is False

    def test_is_empty_sin_texto(self):
        page = PageText(page_num=1, text="   \n  ")
        assert page.is_empty is True

    def test_lines(self):
        page = PageText(page_num=1, text="Línea 1\nLínea 2\nLínea 3")
        assert page.lines == ["Línea 1", "Línea 2", "Línea 3"]


class TestResultadoParseo:
    """Pruebas para el modelo ResultadoParseo."""

    @pytest.fixture
    def resultado_valido(self):
        return ResultadoParseo(
            info_cuenta=InfoCuenta(banco="BBVA", cuenta="123", moneda="MXN"),
            movimientos=[
                Movimiento(
                    fecha=date(2024, 10, 5),
                    concepto="DEPOSITO",
                    referencia="R1",
                    retiro=Decimal("0"),
                    deposito=Decimal("1000"),
                ),
            ],
            resumen=Resumen(
                total_depositos=Decimal("1000"),
                total_retiros=Decimal("0"),
                num_depositos=1,
                num_retiros=0,
            ),
            año=2024,
            mes=10,
            archivo_origen="estado_bbva_oct2024.pdf",
        )

    def test_crear_valido(self, resultado_valido):
        assert resultado_valido.periodo == "2024-10"

    def test_periodo_formato(self, resultado_valido):
        assert resultado_valido.periodo == "2024-10"

    def test_mes_invalido(self):
        with pytest.raises(ValueError, match="Mes fuera de rango"):
            ResultadoParseo(
                info_cuenta=InfoCuenta(banco="X", cuenta="1", moneda="MXN"),
                movimientos=[],
                resumen=Resumen(
                    total_depositos=Decimal("0"),
                    total_retiros=Decimal("0"),
                    num_depositos=0,
                    num_retiros=0,
                ),
                año=2024,
                mes=13,
                archivo_origen="x.pdf",
            )

    def test_año_invalido(self):
        with pytest.raises(ValueError, match="Año fuera de rango"):
            ResultadoParseo(
                info_cuenta=InfoCuenta(banco="X", cuenta="1", moneda="MXN"),
                movimientos=[],
                resumen=Resumen(
                    total_depositos=Decimal("0"),
                    total_retiros=Decimal("0"),
                    num_depositos=0,
                    num_retiros=0,
                ),
                año=1899,
                mes=1,
                archivo_origen="x.pdf",
            )
