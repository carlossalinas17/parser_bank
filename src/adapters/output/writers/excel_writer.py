"""
Adaptador de salida: Escritor de Excel.

Genera archivos Excel con el layout estándar de 2 hojas:
- Hoja 1 (Resumen): Totales de depósitos y retiros.
- Hoja 2 (Movimientos): Detalle de cada movimiento con 9 columnas.

Este adaptador reemplaza las 17 funciones generar_excel() duplicadas
en los extractores originales. Todas compartían el mismo esquema de
columnas pero usaban motores diferentes (xlsxwriter vs openpyxl).
Ahora se centraliza en xlsxwriter exclusivamente.
"""

from pathlib import Path

import pandas as pd

from src.domain.exceptions import OutputError
from src.domain.models.resultado_parseo import ResultadoParseo
from src.domain.ports.output_writer import OutputWriter


class ExcelWriter(OutputWriter):
    """Genera archivos Excel con formato estandarizado."""

    def write_single(self, resultado: ResultadoParseo, output_path: Path) -> Path:
        """Escribe un solo estado de cuenta a Excel.

        Genera un archivo con:
        - Hoja "Resumen": totales de depósitos y retiros.
        - Hoja "Movimientos": detalle de cada movimiento.

        Args:
            resultado: Resultado del parseo de un estado de cuenta.
            output_path: Ruta donde crear el archivo. Si no termina en .xlsx,
                        se le agrega la extensión.

        Returns:
            Ruta del archivo creado.
        """
        # Asegurar extensión .xlsx
        if output_path.suffix.lower() != ".xlsx":
            output_path = output_path.with_suffix(".xlsx")

        # Crear directorio si no existe
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._escribir_excel([resultado], output_path)
        except Exception as e:
            raise OutputError(str(output_path), str(e))

        return output_path

    def write_consolidated(self, resultados: list[ResultadoParseo], output_path: Path) -> Path:
        """Escribe la consolidación de múltiples estados de cuenta.

        Genera un archivo con todos los movimientos de todos los archivos
        en las mismas 2 hojas (Resumen consolidado + Movimientos consolidados).

        Args:
            resultados: Lista de resultados de parseo.
            output_path: Ruta donde crear el archivo consolidado.

        Returns:
            Ruta del archivo creado.
        """
        if not resultados:
            raise OutputError(str(output_path), "No hay resultados para consolidar")

        if output_path.suffix.lower() != ".xlsx":
            output_path = output_path.with_suffix(".xlsx")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            self._escribir_excel(resultados, output_path)
        except Exception as e:
            raise OutputError(str(output_path), str(e))

        return output_path

    # =================================================================
    # MÉTODO PRIVADO: Generación del Excel
    # =================================================================

    def _escribir_excel(self, resultados: list[ResultadoParseo], output_path: Path) -> None:
        """Genera el archivo Excel con las 2 hojas.

        ¿Por qué un método privado compartido?
        Porque write_single y write_consolidated generan el mismo formato,
        solo difieren en cuántos ResultadoParseo reciben.
        """
        # --- Construir datos de Movimientos ---
        filas_movimientos = []
        for resultado in resultados:
            for mov in resultado.movimientos:
                filas_movimientos.append(
                    {
                        "Banco": resultado.info_cuenta.banco,
                        "Cuenta": resultado.info_cuenta.cuenta,
                        "Moneda": resultado.info_cuenta.moneda,
                        "Fecha": mov.fecha.strftime("%d/%m/%Y"),
                        "Fecha.1": mov.fecha.strftime("%d/%m/%Y"),
                        "Concepto": mov.concepto,
                        "Referencia": mov.referencia,
                        "Retiros": float(mov.retiro) if mov.retiro > 0 else 0,
                        "Depósitos": float(mov.deposito) if mov.deposito > 0 else 0,
                    }
                )

        df_movimientos = pd.DataFrame(filas_movimientos)

        # --- Construir datos de Resumen ---
        filas_resumen = []
        for resultado in resultados:
            filas_resumen.append(
                {
                    "Banco": resultado.info_cuenta.banco,
                    "Cuenta": resultado.info_cuenta.cuenta,
                    "Moneda": resultado.info_cuenta.moneda,
                    "Periodo": resultado.periodo,
                    "Total Depósitos": float(resultado.resumen.total_depositos),
                    "Num Depósitos": resultado.resumen.num_depositos,
                    "Total Retiros": float(resultado.resumen.total_retiros),
                    "Num Retiros": resultado.resumen.num_retiros,
                    "Archivo": resultado.archivo_origen,
                }
            )

        df_resumen = pd.DataFrame(filas_resumen)

        # --- Escribir Excel con xlsxwriter ---
        with pd.ExcelWriter(output_path, engine="xlsxwriter") as writer:
            # Hoja 1: Resumen
            df_resumen.to_excel(writer, index=False, sheet_name="Resumen")

            # Hoja 2: Movimientos
            df_movimientos.to_excel(writer, index=False, sheet_name="Movimientos")

            # --- Aplicar formato ---
            workbook = writer.book
            ws_resumen = writer.sheets["Resumen"]
            ws_movimientos = writer.sheets["Movimientos"]

            # Formato para texto (mantener ceros iniciales en cuenta)
            text_format = workbook.add_format({"num_format": "@"})

            # Formato para montos (2 decimales con separador de miles)
            money_format = workbook.add_format({"num_format": "#,##0.00"})

            # --- Formato Hoja Resumen ---
            ws_resumen.set_column("A:A", 12)  # Banco
            ws_resumen.set_column("B:B", 18, text_format)  # Cuenta
            ws_resumen.set_column("C:C", 8)  # Moneda
            ws_resumen.set_column("D:D", 10)  # Periodo
            ws_resumen.set_column("E:E", 18, money_format)  # Total Depósitos
            ws_resumen.set_column("F:F", 14)  # Num Depósitos
            ws_resumen.set_column("G:G", 18, money_format)  # Total Retiros
            ws_resumen.set_column("H:H", 14)  # Num Retiros
            ws_resumen.set_column("I:I", 30)  # Archivo

            # --- Formato Hoja Movimientos ---
            ws_movimientos.set_column("A:A", 10)  # Banco
            ws_movimientos.set_column("B:B", 18, text_format)  # Cuenta
            ws_movimientos.set_column("C:C", 8)  # Moneda
            ws_movimientos.set_column("D:E", 12)  # Fechas
            ws_movimientos.set_column("F:F", 50)  # Concepto
            ws_movimientos.set_column("G:G", 15, text_format)  # Referencia
            ws_movimientos.set_column("H:I", 15, money_format)  # Retiros/Depósitos
