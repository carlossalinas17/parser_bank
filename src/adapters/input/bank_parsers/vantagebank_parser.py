"""
Adaptador de entrada: Parser de estados de cuenta VANTAGE BANK.

Migrado de: extractor_vantagebank_final.py (388 líneas originales)

DIFERENCIA ARQUITECTURAL:
- vs BBVA/Banorte: NO requiere coordenadas X/Y (regex sobre texto).
- vs Santander/Scotiabank: La clasificación NO es por keywords sino por
  SECCIÓN del PDF. Si el movimiento está bajo "DEPOSITOS", es depósito.
  Si está bajo "OTROS DEBITOS" o "RETIROS", es retiro.
- El formato de fecha es AMERICANO: MM-DD (mes primero), sin año.
- El formato de línea es INVERTIDO: CONCEPTO FECHA MONTO
  (la descripción va primero, luego la fecha, luego el monto).
- Moneda default es USD (banco texano).

LÓGICA DE PARSEO (preservada del original):
1. Se detectan secciones: OTROS DEBITOS, DEPOSITOS, RETIROS, DEBITOS.
2. Cada sección termina con "Total", "DESGLOCE", "www." o "PERIODO ACTUAL".
3. Dentro de cada sección, las líneas tienen formato:
   DESCRIPCION MM-DD MONTO (ej: "INACTIVE ACCOUNT FEE 12-31 10.00").
4. El año se infiere de las primeras 30 líneas del texto.
5. La cuenta es un número de 9 dígitos.

BUGS CORREGIDOS vs original:
- Todos los movimientos se clasificaban como retiro (ignoraba la sección).
  → Ahora se pasa el nombre de la sección y se clasifica correctamente.
- float para montos → Decimal.
- Año hardcoded 2024 → extraído del texto.
- try/except vacíos → errores explícitos.
- Dependencia de pytesseract/pdf2image → OCR es responsabilidad del extractor.
"""

import re
from datetime import date
from decimal import Decimal

from src.domain.exceptions import ParseError
from src.domain.models.info_cuenta import InfoCuenta
from src.domain.models.movimiento import Movimiento
from src.domain.models.page_text import PageText
from src.domain.models.resultado_parseo import ResultadoParseo
from src.domain.models.resumen import Resumen
from src.domain.ports.bank_parser import BankParser
from src.domain.shared.money import parse_money_safe


class VantageBankParser(BankParser):
    """Parser de estados de cuenta Vantage Bank.

    La diferencia principal con todos los otros parsers es que la
    clasificación depósito/retiro se determina por la SECCIÓN del PDF
    donde aparece el movimiento, no por keywords del concepto.

    Vantage Bank es un banco texano, así que:
    - Las fechas son formato americano: MM-DD.
    - La moneda default es USD.
    - Los textos pueden estar en inglés.
    """

    # Marcadores que inician una sección de movimientos
    # El tipo (deposito/retiro) se infiere del nombre de la sección
    _SECTION_START_PATTERN: re.Pattern[str] = re.compile(
        r"(OTROS\s+DEBITOS|DEPOSITOS|DEPÓSITOS|RETIROS|DEBITOS|DÉBITOS)",
        re.IGNORECASE,
    )

    # Palabras en el nombre de sección que indican depósito
    _DEPOSIT_SECTIONS: list[str] = [
        "DEPOSITO",
        "DEPÓSITO",
    ]

    # Marcadores que terminan una sección de movimientos
    _SECTION_END_MARKERS: list[str] = [
        "Total",
        "DESGLOCE",
        "www.",
        "PERIODO ACTUAL",
    ]

    # Patrón de movimiento: DESCRIPCION MM-DD MONTO
    # Ejemplo: "INACTIVE ACCOUNT FEE 12-31 10.00"
    # Ejemplo: "WIRE TRANSFER IN 1-15 50,000.00"
    _MOVEMENT_PATTERN: re.Pattern[str] = re.compile(
        r"^(.+?)\s+(\d{1,2}-\d{1,2})\s+([\d,]+\.\d{2})$"
    )

    # Patrón de cuenta: 9 dígitos después de "cuenta"
    _ACCOUNT_PATTERN: re.Pattern[str] = re.compile(r"cuenta\s+(\d{9})", re.IGNORECASE)

    # Líneas de encabezado que deben ignorarse dentro de secciones
    _HEADER_LINES: list[str] = [
        "Descripción",
        "Descripcion",
        "Fecha",
    ]

    @property
    def bank_name(self) -> str:
        return "VANTAGE_BANK"

    def parse(self, pages: list[PageText], file_name: str = "") -> ResultadoParseo:
        """Parsea un estado de cuenta Vantage Bank completo."""
        if not pages:
            raise ParseError("VANTAGE_BANK", file_name, "No se recibieron páginas")

        # Concatenar todo el texto (Vantage trabaja sobre texto completo)
        texto_completo = "\n".join(p.text for p in pages)

        info_cuenta = self._extraer_info_cuenta(texto_completo)
        año = self._extraer_año(texto_completo, file_name)
        mes = self._extraer_mes(texto_completo, año)
        movimientos = self._extraer_movimientos(texto_completo, año)
        resumen = self._calcular_resumen(movimientos)

        return ResultadoParseo(
            info_cuenta=info_cuenta,
            movimientos=movimientos,
            resumen=resumen,
            año=año,
            mes=mes,
            archivo_origen=file_name,
        )

    # =================================================================
    # Extracción de info de cuenta
    # =================================================================

    def _extraer_info_cuenta(self, texto: str) -> InfoCuenta:
        """Extrae banco, cuenta y moneda.

        Vantage Bank es un banco texano, así que la moneda default
        es USD. Solo se cambia a MXN si se detecta explícitamente.
        La cuenta son 9 dígitos (ej: 107072718).
        """
        cuenta = ""
        moneda = "USD"  # Default para Vantage Bank (banco texano)

        match = self._ACCOUNT_PATTERN.search(texto)
        if match:
            cuenta = match.group(1)

        # Solo las primeras 2000 chars para detectar moneda
        encabezado = texto[:2000].upper()
        if "MXN" in encabezado:
            moneda = "MXN"

        if not cuenta:
            cuenta = "SIN_CUENTA"

        return InfoCuenta(banco="VANTAGE_BANK", cuenta=cuenta, moneda=moneda)

    # =================================================================
    # Extracción de año y mes
    # =================================================================

    def _extraer_año(self, texto: str, file_name: str) -> int:
        """Extrae el año del encabezado.

        Vantage Bank no incluye el año en cada movimiento (solo MM-DD),
        así que se busca un año 20XX en las primeras líneas del texto.
        """
        lineas = texto.split("\n")[:30]
        for linea in lineas:
            match = re.search(r"\b(20\d{2})\b", linea)
            if match:
                return int(match.group(1))

        raise ParseError(
            "VANTAGE_BANK",
            file_name,
            "No se pudo determinar el año del estado de cuenta.",
        )

    def _extraer_mes(self, texto: str, año: int) -> int:
        """Extrae el mes del estado de cuenta.

        Busca patrones comunes de periodo en el encabezado.
        Si no encuentra, intenta inferir del primer movimiento.
        """
        encabezado = texto[:2000]

        # Buscar patrones de mes en inglés (Vantage es banco texano)
        meses_en = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }

        # Patrón: "Dec 31, 2024" o "January 2025"
        for nombre, num in meses_en.items():
            if re.search(nombre, encabezado, re.IGNORECASE):
                return num

        # Fallback: buscar primer movimiento con fecha MM-DD
        match = self._MOVEMENT_PATTERN.search(texto)
        if match:
            fecha_str = match.group(2)
            parts = fecha_str.split("-")
            if len(parts) == 2:
                try:
                    return int(parts[0])
                except ValueError:
                    pass

        return 1  # Default a enero

    # =================================================================
    # Extracción de movimientos
    # =================================================================

    def _extraer_movimientos(self, texto: str, año: int) -> list[Movimiento]:
        """Extrae movimientos de todas las secciones.

        A diferencia de los otros parsers, aquí la clasificación
        depósito/retiro depende de EN QUÉ SECCIÓN está el movimiento:
        - Sección "DEPOSITOS" → depósito.
        - Sección "OTROS DEBITOS", "RETIROS", "DEBITOS" → retiro.

        BUG CORREGIDO: El original ignoraba la sección y clasificaba
        TODO como retiro. Ahora se pasa el tipo de sección.
        """
        lineas = texto.split("\n")
        movimientos: list[Movimiento] = []
        en_seccion = False
        tipo_seccion = "retiro"  # Default

        for linea in lineas:
            linea_stripped = linea.strip()

            # Detectar inicio de sección
            match_seccion = self._SECTION_START_PATTERN.search(linea_stripped)
            if match_seccion:
                en_seccion = True
                nombre_seccion = match_seccion.group(1).upper()
                tipo_seccion = self._clasificar_seccion(nombre_seccion)
                continue

            # Detectar fin de sección
            if en_seccion and self._es_fin_seccion(linea_stripped):
                en_seccion = False
                continue

            # Parsear movimiento dentro de sección
            if en_seccion:
                mov = self._parsear_movimiento(linea_stripped, año, tipo_seccion)
                if mov is not None:
                    movimientos.append(mov)

        return movimientos

    def _parsear_movimiento(self, linea: str, año: int, tipo: str) -> Movimiento | None:
        """Parsea una línea de movimiento.

        Formato: DESCRIPCION MM-DD MONTO
        Ejemplo: "INACTIVE ACCOUNT FEE 12-31 10.00"

        El tipo (deposito/retiro) viene de la sección, no de keywords.
        """
        if not linea:
            return None

        # Ignorar encabezados de sección
        if any(linea.startswith(h) for h in self._HEADER_LINES):
            return None

        match = self._MOVEMENT_PATTERN.match(linea)
        if not match:
            return None

        descripcion = match.group(1).strip()
        fecha_str = match.group(2)  # MM-DD
        monto_str = match.group(3)

        # Parsear fecha (formato americano MM-DD)
        fecha = self._parsear_fecha_americana(fecha_str, año)
        if fecha is None:
            return None

        monto = parse_money_safe(monto_str)
        if monto <= Decimal("0"):
            return None

        deposito = monto if tipo == "deposito" else Decimal("0")
        retiro = monto if tipo == "retiro" else Decimal("0")

        return Movimiento(
            fecha=fecha,
            concepto=descripcion,
            referencia="",
            retiro=retiro,
            deposito=deposito,
        )

    # =================================================================
    # Helpers
    # =================================================================

    def _clasificar_seccion(self, nombre: str) -> str:
        """Determina si una sección contiene depósitos o retiros."""
        nombre_upper = nombre.upper()
        if any(dep in nombre_upper for dep in self._DEPOSIT_SECTIONS):
            return "deposito"
        return "retiro"

    def _es_fin_seccion(self, linea: str) -> bool:
        """Detecta si una línea marca el fin de una sección de movimientos."""
        return any(linea.startswith(marker) for marker in self._SECTION_END_MARKERS)

    @staticmethod
    def _parsear_fecha_americana(fecha_str: str, año: int) -> date | None:
        """Convierte fecha MM-DD a objeto date.

        Vantage Bank usa formato americano: mes primero, día después.
        Ejemplo: "12-31" → 31 de diciembre.
        """
        parts = fecha_str.split("-")
        if len(parts) != 2:
            return None

        try:
            mes = int(parts[0])
            dia = int(parts[1])
            return date(año, mes, dia)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _calcular_resumen(movimientos: list[Movimiento]) -> Resumen:
        """Calcula totales a partir de los movimientos extraídos."""
        total_depositos = sum(
            (m.deposito for m in movimientos if m.deposito > Decimal("0")),
            Decimal("0"),
        )
        total_retiros = sum(
            (m.retiro for m in movimientos if m.retiro > Decimal("0")),
            Decimal("0"),
        )
        num_depositos = sum(1 for m in movimientos if m.deposito > Decimal("0"))
        num_retiros = sum(1 for m in movimientos if m.retiro > Decimal("0"))

        return Resumen(
            total_depositos=total_depositos,
            total_retiros=total_retiros,
            num_depositos=num_depositos,
            num_retiros=num_retiros,
        )
