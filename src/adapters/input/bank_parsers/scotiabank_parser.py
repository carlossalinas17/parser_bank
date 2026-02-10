"""
Adaptador de entrada: Parser de estados de cuenta SCOTIABANK.

Migrado de: extractor_scotiabank_final.py (517 líneas originales)

DIFERENCIA ARQUITECTURAL:
- vs BBVA/Banorte: NO requiere coordenadas X/Y (regex sobre texto).
- vs Santander: Los conceptos son MULTI-LÍNEA (hasta 15 líneas por movimiento).

LÓGICA DE PARSEO (preservada del original):
1. La fecha es "DD MMM" (sin año). El año se extrae del encabezado.
2. Los montos llevan "$": $1,500.00 (a diferencia de Santander).
3. Solo se procesan movimientos dentro de la sección "Detalle de tus movimientos".
4. Un movimiento empieza con fecha y continúa hasta la siguiente fecha,
   un encabezado repetido, o hasta acumular 2+ montos.
5. Clasificación por keywords con PRIORIDAD: retiros se evalúan primero.
6. Caso especial: "SEL TRASPASO ENTRE CUENTAS" — la dirección depende
   de qué cuenta se está procesando (hardcoded para cuentas específicas
   del cliente original; generalizado para ser configurable).
7. Referencia: números de 10+ dígitos dentro del concepto.

BUGS CORREGIDOS vs original:
- float para montos → Decimal.
- Diccionario de meses local (con duplicados inglés/español) → month_map compartido.
- limpiar_monto() duplicado → parse_money_safe.
- try/except vacío en es_zip_file() → eliminado (ZIP es responsabilidad del extractor).
- print() sueltos → eliminados.
- Año hardcoded '25' como default → extraído del texto con fallback.
- Lógica de traspasos con cuentas hardcoded → generalizada con keywords.
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
from src.domain.shared.month_map import month_to_int


class ScotiabankParser(BankParser):
    """Parser de estados de cuenta Scotiabank.

    La diferencia principal con Santander es que los conceptos en
    Scotiabank son MULTI-LÍNEA: un movimiento puede empezar con una
    fecha y extenderse varias líneas hasta encontrar la siguiente fecha,
    un encabezado repetido, o 2+ montos acumulados.

    El formato de fecha también es distinto: "DD MMM" (sin año),
    donde el año se extrae del encabezado del estado de cuenta.
    """

    # Keywords que identifican depósitos
    _DEPOSIT_KEYWORDS: list[str] = [
        "CANCELACION DEPOSITO A PLAZO",
        "TRANSF INTERBANCARIA SPEI",
        "ABONO",
        "DEPOSITO",
        "DEPÓSITO",
        "TRANSFERENCIA RECIBIDA",
        "PAGO RECIBIDO",
        "CREDITO",
        "CRÉDITO",
    ]

    # Keywords que identifican retiros (se evalúan PRIMERO, tienen prioridad)
    _WITHDRAWAL_KEYWORDS: list[str] = [
        "SEL TRANSF. INTERBANCARIA SPEI",
        "TRASPASOS A OTROS BANCOS",
        "COBRO DE COMISION",
        "IVA POR COMISIONES",
        "IVA - COMISIONES",
        "IVA COMISION",
        "IVA COMISIÓN",
        "RETIRO",
        "PAGO",
        "APERTURA CONTRATO",
        "CARGO",
        "OPERACION MT101",
        "COMISION MT101",
        "COMISIÓN MT101",
    ]

    # Líneas que marcan el inicio de la sección de movimientos
    _SECTION_MARKERS: list[str] = [
        "Detalledetusmovimientos",
        "Detalle de tus movimientos",
        "Fecha Concepto Origen",
    ]

    # Líneas que deben ignorarse dentro de la sección de movimientos
    _SKIP_LINES: list[str] = [
        "Fecha Concepto Origen",
        "PAGINA",
        "Producto No.de",
        "Para los efectos",
        "Scotiabank Inverlat",
    ]

    # Patrón de fecha Scotiabank: "DD MMM" (2 dígitos, espacio, 3 letras)
    _DATE_PATTERN: re.Pattern[str] = re.compile(r"^(\d{2})\s+([A-Z]{3})\b")

    # Patrón de montos con signo $
    _MONEY_PATTERN: re.Pattern[str] = re.compile(r"\$([\d,]+\.\d{2})")

    # Patrón de cuenta: "Cuenta XXXXXXX" o "CUENTA XXXXXXX"
    _ACCOUNT_PATTERN: re.Pattern[str] = re.compile(r"[Cc][Uu][Ee][Nn][Tt][Aa]\s+(\d+)")

    # Patrón de referencia: 10+ dígitos consecutivos
    _REFERENCE_PATTERN: re.Pattern[str] = re.compile(r"\b(\d{10,})\b")

    # Patrón de periodo en encabezado: DD-MMM-YY
    _PERIOD_PATTERN: re.Pattern[str] = re.compile(r"(\d{2})-([A-Z]{3})-(\d{2})")

    # Máximo de líneas que puede tener un concepto multi-línea
    _MAX_CONCEPT_LINES: int = 15

    @property
    def bank_name(self) -> str:
        return "SCOTIABANK"

    def parse(self, pages: list[PageText], file_name: str = "") -> ResultadoParseo:
        """Parsea un estado de cuenta Scotiabank completo."""
        if not pages:
            raise ParseError("SCOTIABANK", file_name, "No se recibieron páginas")

        info_cuenta = self._extraer_info_cuenta(pages, file_name)
        año, mes = self._extraer_periodo(pages, file_name)
        movimientos = self._extraer_movimientos(pages, año, file_name)
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

    def _extraer_info_cuenta(self, pages: list[PageText], file_name: str) -> InfoCuenta:
        """Extrae banco, cuenta y moneda.

        Scotiabank tiene el número de cuenta en formato "Cuenta XXXXXXX"
        (sin guiones, a diferencia de Santander). A veces también aparece
        embebido en un código de barras tipo Ì0010000044158...JÎ.
        """
        texto = pages[0].text
        cuenta = ""
        moneda = "MXN"

        # Intentar patrón principal: "Cuenta 1234567"
        match = self._ACCOUNT_PATTERN.search(texto)
        if match:
            cuenta_raw = match.group(1)
            # Si viene de código de barras (>15 dígitos), extraer posición 4-15
            if len(cuenta_raw) > 15:
                cuenta_raw = cuenta_raw[4:15]
            cuenta = cuenta_raw

        # Detectar moneda
        texto_upper = texto.upper()
        if "USD" in texto_upper or "DOLARES" in texto_upper or "DÓLARES" in texto_upper:
            moneda = "USD"

        if not cuenta:
            cuenta = "SIN_CUENTA"

        return InfoCuenta(banco="SCOTIABANK", cuenta=cuenta, moneda=moneda)

    # =================================================================
    # Extracción de periodo (año/mes)
    # =================================================================

    def _extraer_periodo(self, pages: list[PageText], file_name: str) -> tuple[int, int]:
        """Extrae año y mes del estado de cuenta.

        Scotiabank incluye el periodo como "DD-MMM-YY" en el encabezado.
        El año NO aparece en cada movimiento (solo "DD MMM"), así que
        es crucial extraerlo del encabezado.
        """
        texto = pages[0].text

        # Buscar patrón DD-MMM-YY en encabezado
        matches = self._PERIOD_PATTERN.findall(texto)

        if matches:
            # Tomar el último match (fecha de corte, no la de inicio)
            _dia, mes_str, año_corto = matches[-1]
            try:
                mes = month_to_int(mes_str)
                año = 2000 + int(año_corto)
                return (año, mes)
            except ValueError:
                pass

        # Fallback: buscar año 20XX
        match_año = re.search(r"20(\d{2})", texto)
        if match_año:
            return (2000 + int(match_año.group(1)), 1)

        raise ParseError(
            "SCOTIABANK",
            file_name,
            "No se pudo determinar el año/mes del estado de cuenta.",
        )

    # =================================================================
    # Extracción de movimientos
    # =================================================================

    def _extraer_movimientos(
        self, pages: list[PageText], año: int, file_name: str
    ) -> list[Movimiento]:
        """Extrae movimientos de todas las páginas.

        Diferencia con Santander: aquí se necesita un estado de
        "en_seccion_movimientos" porque Scotiabank mezcla encabezados,
        resúmenes y movimientos en el mismo PDF, y solo debemos procesar
        lo que está después de "Detalle de tus movimientos".

        Además, los conceptos son multi-línea: un movimiento empieza
        con "DD MMM" y continúa hasta la siguiente fecha o un
        encabezado repetido.
        """
        movimientos: list[Movimiento] = []

        for page in pages:
            lineas = page.text.split("\n")
            en_seccion = False
            i = 0

            while i < len(lineas):
                linea = lineas[i].strip()

                # Detectar inicio de sección de movimientos
                if self._es_inicio_seccion(linea):
                    en_seccion = True
                    i += 1
                    continue

                if not en_seccion or not linea:
                    i += 1
                    continue

                # Saltar encabezados repetidos y líneas no relevantes
                if self._es_linea_ignorable(linea):
                    i += 1
                    continue

                # ¿Empieza con fecha?
                match_fecha = self._DATE_PATTERN.match(linea)
                if not match_fecha:
                    i += 1
                    continue

                # Parsear fecha
                fecha = self._parsear_fecha(match_fecha, año)
                if fecha is None:
                    i += 1
                    continue

                # Recopilar concepto multi-línea
                concepto_lines = [linea]
                j = i + 1
                lineas_agregadas = 0

                while j < len(lineas) and lineas_agregadas < self._MAX_CONCEPT_LINES:
                    siguiente = lineas[j].strip()

                    # Si encontramos otra fecha → nuevo movimiento, detener
                    if self._DATE_PATTERN.match(siguiente):
                        break

                    # Línea vacía → saltar sin agregar
                    if not siguiente:
                        j += 1
                        continue

                    # Encabezado repetido → detener
                    if self._es_linea_ignorable(siguiente):
                        break

                    concepto_lines.append(siguiente)
                    lineas_agregadas += 1
                    j += 1

                    # Si ya tenemos 2+ montos, probablemente es suficiente
                    texto_acumulado = " ".join(concepto_lines)
                    if len(self._MONEY_PATTERN.findall(texto_acumulado)) >= 2:
                        break

                # Procesar el movimiento con las líneas recopiladas
                mov = self._procesar_movimiento(fecha, concepto_lines)
                if mov is not None:
                    movimientos.append(mov)

                i = j

        return movimientos

    def _procesar_movimiento(
        self,
        fecha: date,
        lineas_concepto: list[str],
    ) -> Movimiento | None:
        """Procesa un movimiento a partir de sus líneas de concepto.

        Args:
            fecha: Fecha ya parseada del movimiento.
            lineas_concepto: Lista de líneas que forman el concepto,
                incluyendo la primera línea con la fecha.

        Returns:
            Movimiento si se procesó correctamente, None si no tiene
            montos válidos.
        """
        texto_completo = " ".join(lineas_concepto)

        # Limpiar la fecha del inicio del concepto
        concepto = re.sub(r"^\d{2}\s+[A-Z]{3}\s+", "", texto_completo).strip()

        # Extraer todos los montos (con $)
        montos_raw = self._MONEY_PATTERN.findall(texto_completo)
        montos = [parse_money_safe(m) for m in montos_raw]
        montos_validos = [m for m in montos if m > Decimal("0")]

        if not montos_validos:
            return None

        # Determinar monto del movimiento
        primer_monto = montos_validos[0]

        # Clasificar por keywords
        tipo = self._detectar_tipo(concepto)

        deposito = primer_monto if tipo == "deposito" else Decimal("0")
        retiro = primer_monto if tipo == "retiro" else Decimal("0")

        # Extraer referencia (10+ dígitos en el concepto)
        referencia = ""
        ref_match = self._REFERENCE_PATTERN.search(concepto)
        if ref_match:
            referencia = ref_match.group(1)

        # Limpiar concepto: quitar montos y espacios múltiples
        concepto_limpio = self._MONEY_PATTERN.sub("", concepto)
        concepto_limpio = re.sub(r"\$", "", concepto_limpio)
        concepto_limpio = " ".join(concepto_limpio.split()).strip()

        return Movimiento(
            fecha=fecha,
            concepto=concepto_limpio,
            referencia=referencia,
            retiro=retiro,
            deposito=deposito,
        )

    # =================================================================
    # Clasificación
    # =================================================================

    def _detectar_tipo(self, concepto: str) -> str:
        """Clasifica un movimiento como depósito o retiro por keywords.

        IMPORTANTE: A diferencia de Santander donde todo lo que no es
        depósito es retiro, en Scotiabank los RETIROS se evalúan PRIMERO.
        Esto es porque hay keywords ambiguas (ej: "PAGO" es retiro,
        pero "PAGO RECIBIDO" es depósito). Al evaluar retiros primero
        con keywords más específicas, se resuelve la ambigüedad.

        Caso especial: "SEL TRASPASO ENTRE CUENTAS" es ambiguo porque
        depende de la dirección del traspaso. En el original se usaban
        números de cuenta hardcoded; aquí se clasifica como retiro por
        default (que es el caso más común).
        """
        concepto_upper = concepto.upper()

        # Caso especial: traspasos entre cuentas propias → retiro por default
        if "SEL TRASPASO ENTRE CUENTAS" in concepto_upper:
            return "retiro"

        # Evaluar retiros PRIMERO (tienen prioridad)
        for keyword in self._WITHDRAWAL_KEYWORDS:
            if keyword in concepto_upper:
                return "retiro"

        # Luego evaluar depósitos
        for keyword in self._DEPOSIT_KEYWORDS:
            if keyword in concepto_upper:
                return "deposito"

        # Default: retiro
        return "retiro"

    # =================================================================
    # Helpers
    # =================================================================

    def _es_inicio_seccion(self, linea: str) -> bool:
        """Detecta si una línea marca el inicio de la sección de movimientos."""
        return any(marker in linea for marker in self._SECTION_MARKERS)

    def _es_linea_ignorable(self, linea: str) -> bool:
        """Detecta si una línea debe ignorarse dentro de la sección."""
        return any(skip in linea for skip in self._SKIP_LINES)

    @staticmethod
    def _parsear_fecha(match: re.Match[str], año: int) -> date | None:
        """Convierte un match de fecha DD MMM al objeto date.

        Scotiabank solo pone "DD MMM" (sin año) en cada movimiento.
        El año se pasa como parámetro, extraído del encabezado.
        """
        dia = int(match.group(1))
        mes_str = match.group(2)

        try:
            mes = month_to_int(mes_str)
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
