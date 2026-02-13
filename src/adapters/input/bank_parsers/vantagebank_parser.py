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
    # El tipo (deposito/retiro) se infiere del nombre de la sección.
    #
    # IMPORTANTE: "OTROS CREDITOS" es la sección de DEPÓSITOS en Vantage.
    # No confundir con "OTROS DEBITOS" que es retiros.
    # El patrón usa alternancia ordenada: las opciones más específicas
    # (OTROS CREDITOS, OTROS DEBITOS) van antes que las genéricas
    # (CREDITOS, DEBITOS) para evitar matcheos parciales.
    _SECTION_START_PATTERN: re.Pattern[str] = re.compile(
        r"(OTROS\s+CREDITOS|OTROS\s+CRÉDITOS"
        r"|OTROS\s+DEBITOS|OTROS\s+DÉBITOS"
        r"|DEPOSITOS|DEPÓSITOS"
        r"|CREDITOS|CRÉDITOS"
        r"|RETIROS"
        r"|DEBITOS|DÉBITOS)",
        re.IGNORECASE,
    )

    # Palabras en el nombre de sección que indican depósito.
    # "CREDITO" cubre tanto "OTROS CREDITOS" como "CREDITOS".
    _DEPOSIT_SECTIONS: list[str] = [
        "DEPOSITO",
        "DEPÓSITO",
        "CREDITO",
        "CRÉDITO",
    ]

    # Marcadores que terminan una sección de movimientos.
    # Incluye variantes OCR como "www.vantage." (con espacio)
    _SECTION_END_MARKERS: list[str] = [
        "Total",
        "DESGLOCE",
        "www.",
        "PERIODO ACTUAL",
        "CONCILIACION",
        "SALDO DIARIO",
    ]

    # Patrón de movimiento: DESCRIPCION MM-DD MONTO
    # Ejemplo: "INACTIVE ACCOUNT FEE 12-31 10.00"
    # Ejemplo: "WIRE TRANSFER IN 1-15 50,000.00"
    #
    # TOLERANCIA OCR: El regex permite variantes comunes de OCR:
    # - Fechas con mes 0: "0-07" (OCR perdió el "1" de "10-07")
    # - Montos con espacios: "177 446.35" en vez de "177,446.35"
    # - Montos con ", " antes de centavos: "709,008, 00"
    # - Montos con ". " antes de centavos: "3,128,696. 87"
    # - Montos con punto al final sin centavos bien: "9.178.00"
    #
    # El regex es más permisivo y la normalización se hace después.
    _MOVEMENT_PATTERN: re.Pattern[str] = re.compile(
        r"^(.+?)\s+(\d{1,2}-\d{1,2})\s+([\d,.\s]+\d)\s*$"
    )

    # Patrón de cuenta: dígitos después de "cuenta" (6-9 dígitos para
    # cubrir variaciones de OCR que pueden perder un dígito)
    _ACCOUNT_PATTERN: re.Pattern[str] = re.compile(r"cuenta\s+(\d{6,9})", re.IGNORECASE)

    # Líneas de encabezado que deben ignorarse dentro de secciones
    _HEADER_LINES: list[str] = [
        "Descripción",
        "Descripcion",
        "Descripci",  # OCR a veces corta la ó
        "Fecha",
    ]

    # Patrón para detectar si una línea es continuación de un movimiento
    # (NO empieza con fecha MM-DD y NO es fin de sección ni encabezado)
    _DATE_PREFIX_PATTERN: re.Pattern[str] = re.compile(r"^\d{1,2}-\d{1,2}\b")

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

        # Solo las primeras 2000 chars para detectar moneda.
        # IMPORTANTE: Buscar "MXN" como indicador de moneda del estado,
        # NO como parte de descripciones de transferencia.
        # "WIRE MXN TO PRADERAS" contiene "MXN" pero NO indica moneda MXN.
        # Los indicadores válidos son: "Moneda: MXN", "MXN$", o "MXN" aislado
        # en contexto de encabezado (antes de la sección de movimientos).
        encabezado = texto[:2000].upper()

        # Buscar MXN como palabra aislada en contexto de moneda,
        # excluyendo patrones como "WIRE MXN" que son transferencias.
        if re.search(r"(?<!WIRE\s)(?<!WIRE\s\s)MXN(?!\s+TO\b)", encabezado):
            # Verificación extra: si "WIRE MXN" aparece, probablemente
            # es una transferencia, no un indicador de moneda.
            # Solo aceptar si hay un indicador más fuerte como "Moneda"
            if "WIRE MXN" in encabezado:
                if re.search(r"MONEDA.*MXN|MXN.*MONEDA|DIVISA.*MXN", encabezado):
                    moneda = "MXN"
            else:
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

        TOLERANCIA OCR: Tesseract a veces corrompe el último dígito del año,
        produciendo "202�" o "202$" en vez de "2025". Si no se encuentra un
        año completo en el texto, se intenta extraer del nombre del archivo
        (que sigue la convención "N.- Vantage Bank XXXXXX mes YYYY.pdf").
        """
        # Intento 1: buscar año completo 20XX en las primeras 30 líneas
        lineas = texto.split("\n")[:30]
        for linea in lineas:
            match = re.search(r"\b(20\d{2})\b", linea)
            if match:
                return int(match.group(1))

        # Intento 2: buscar año parcial "202" seguido de caracter corrupto OCR
        # Ejemplo: "May31,202�" → detectar "202" y asumir dígito faltante
        for linea in lineas:
            match = re.search(r"\b(20\d)\D", linea)
            if match:
                año_parcial = match.group(1)  # "202"
                # Intentar extraer el dígito faltante del nombre del archivo
                match_file = re.search(r"(20\d{2})", file_name)
                if match_file and match_file.group(1).startswith(año_parcial):
                    return int(match_file.group(1))

        # Intento 3: extraer año directamente del nombre del archivo
        match_file = re.search(r"\b(20\d{2})\b", file_name)
        if match_file:
            return int(match_file.group(1))

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
        - Sección "OTROS CREDITOS", "DEPOSITOS" → depósito.
        - Sección "OTROS DEBITOS", "RETIROS", "DEBITOS" → retiro.

        MULTI-LÍNEA: Vantage Bank tiene movimientos donde la descripción
        continúa en la siguiente línea. Ejemplo:
            WIRE TRANSFER RODAMIENTOS Y                    10-07   1,809.60
            ACCESORBNMXMKMMXXX20251007MMQFMP29000248

        La primera línea tiene fecha+monto (matchea _MOVEMENT_PATTERN).
        La segunda no tiene fecha ni monto → es continuación.
        Se detecta porque NO empieza con fecha y NO es fin de sección.

        TOLERANCIA OCR: Las líneas se normalizan antes del parseo para
        corregir artefactos comunes de Tesseract (espacios en montos,
        dígitos perdidos en fechas, etc.).
        """
        lineas = texto.split("\n")
        movimientos: list[Movimiento] = []
        en_seccion = False
        tipo_seccion = "retiro"  # Default
        mes_estado = self._extraer_mes(texto, año)

        i = 0
        while i < len(lineas):
            linea_stripped = lineas[i].strip()

            # Detectar inicio de sección
            match_seccion = self._SECTION_START_PATTERN.search(linea_stripped)
            if match_seccion:
                en_seccion = True
                nombre_seccion = match_seccion.group(1).upper()
                tipo_seccion = self._clasificar_seccion(nombre_seccion)
                i += 1
                continue

            # Detectar fin de sección
            if en_seccion and self._es_fin_seccion(linea_stripped):
                en_seccion = False
                i += 1
                continue

            if not en_seccion:
                i += 1
                continue

            # Intentar parsear como movimiento
            linea_norm = self._normalizar_linea_ocr(linea_stripped)
            mov = self._parsear_movimiento(linea_norm, año, tipo_seccion, mes_estado)

            if mov is not None:
                # Buscar líneas de continuación DESPUÉS del movimiento.
                # Una continuación es una línea que:
                # 1. No está vacía
                # 2. No matchea el patrón de movimiento (no tiene fecha+monto)
                # 3. No es fin de sección
                # 4. No es encabezado repetido
                j = i + 1
                continuaciones: list[str] = []

                while j < len(lineas):
                    sig = lineas[j].strip()

                    if not sig:
                        j += 1
                        continue

                    # Si es fin de sección → detener
                    if self._es_fin_seccion(sig):
                        break

                    # Si es encabezado → detener
                    if any(sig.startswith(h) for h in self._HEADER_LINES):
                        break

                    # Si matchea como movimiento → detener (nuevo mov)
                    sig_norm = self._normalizar_linea_ocr(sig)
                    if self._MOVEMENT_PATTERN.match(sig_norm):
                        break

                    # Si empieza con sección → detener
                    if self._SECTION_START_PATTERN.search(sig):
                        break

                    # Es continuación → agregar al concepto
                    continuaciones.append(sig)
                    j += 1

                if continuaciones:
                    mov = Movimiento(
                        fecha=mov.fecha,
                        concepto=mov.concepto + " " + " ".join(continuaciones),
                        referencia=mov.referencia,
                        retiro=mov.retiro,
                        deposito=mov.deposito,
                    )

                movimientos.append(mov)
                i = j  # Saltar a después de las continuaciones
            else:
                i += 1

        return movimientos

    def _parsear_movimiento(
        self, linea: str, año: int, tipo: str, mes_estado: int = 0
    ) -> Movimiento | None:
        """Parsea una línea de movimiento.

        Formato: DESCRIPCION MM-DD MONTO
        Ejemplo: "INACTIVE ACCOUNT FEE 12-31 10.00"

        El tipo (deposito/retiro) viene de la sección, no de keywords.

        Args:
            linea: Línea ya normalizada (sin artefactos OCR gruesos).
            año: Año del estado de cuenta.
            tipo: "deposito" o "retiro" (según la sección).
            mes_estado: Mes del estado de cuenta, para corregir
                        fechas OCR con mes=0 (ej: "0-07" → "10-07").
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
        fecha = self._parsear_fecha_americana(fecha_str, año, mes_estado)
        if fecha is None:
            return None

        # Normalizar monto OCR y parsear
        monto = self._parsear_monto_ocr(monto_str)
        if monto is None or monto <= Decimal("0"):
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
    def _parsear_fecha_americana(fecha_str: str, año: int, mes_estado: int = 0) -> date | None:
        """Convierte fecha MM-DD a objeto date.

        Vantage Bank usa formato americano: mes primero, día después.
        Ejemplo: "12-31" → 31 de diciembre.

        TOLERANCIA OCR:
        1. Si mes=0 (OCR perdió un dígito, ej: "0-07" → "10-07"),
           se usa el mes del estado de cuenta como fallback.
        2. Si el día es inválido (>último día del mes, ej: "10-34"),
           se clampea al último día del mes. Esto maneja el error
           OCR común donde "31"→"34" (Tesseract confunde "1"→"4").
        """
        import calendar

        parts = fecha_str.split("-")
        if len(parts) != 2:
            return None

        try:
            mes = int(parts[0])
            dia = int(parts[1])

            # Fix OCR: mes=0 → usar mes del estado de cuenta
            if mes == 0 and mes_estado > 0:
                mes = mes_estado

            if mes < 1 or mes > 12:
                return None
            if dia < 1:
                return None

            # Fix OCR: día > último día del mes → clampear
            # Ejemplo: "10-34" (OCR de "10-31") → usar 31 (último de oct)
            # Solo aplica para días "cercanos" (32-39) para no aceptar
            # errores grotescos como "10-99".
            ultimo_dia = calendar.monthrange(año, mes)[1]
            if dia > ultimo_dia and dia <= ultimo_dia + 8:
                dia = ultimo_dia

            return date(año, mes, dia)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _normalizar_linea_ocr(linea: str) -> str:
        """Normaliza artefactos OCR comunes en una línea de movimiento.

        El OCR de Tesseract introduce errores predecibles en los montos
        que aparecen al final de cada línea. Esta función los corrige
        ANTES de intentar matchear con el regex de movimiento.

        IMPORTANTE: Solo modifica la porción de MONTO de la línea
        (después de la fecha MM-DD). Nunca toca la descripción ni
        la fecha para evitar corromper el parseo.

        Artefactos corregidos:
        1. Espacio antes de centavos: "72,848 00" → "72,848.00"
        2. Coma+espacio antes de centavos: "709,008, 00" → "709,008.00"
        3. Punto+espacio antes de centavos: "3,128,696. 87" → "3,128,696.87"
        4. Espacio entre grupos de miles: "1,000 000.00" → "1,000,000.00"
           o "177 446.35" → "177,446.35"
        """
        # Primero localizar la fecha MM-DD para saber dónde empieza el monto
        date_match = re.search(r"\d{1,2}-\d{1,2}\s+", linea)
        if not date_match:
            return linea

        # Separar: prefijo (desc + fecha) | monto_part (todo después de la fecha)
        monto_start = date_match.end()
        prefijo = linea[:monto_start]
        monto_part = linea[monto_start:]

        if not monto_part.strip():
            return linea

        # Ahora normalizar SOLO la parte del monto:

        # Patrón 1: "coma/punto + espacio + 2 dígitos" al final
        #   "709,008, 00" → "709,008.00"
        #   "3,128,696. 87" → "3,128,696.87"
        monto_part = re.sub(r"([,.])\s+(\d{2})\s*$", r".\2", monto_part)

        # Patrón 2: "dígito + espacio + 2 dígitos" al final (sin separador)
        #   "72,848 00" → "72,848.00"
        monto_part = re.sub(r"(\d)\s+(\d{2})\s*$", r"\1.\2", monto_part)

        # Patrón 3: espacios entre grupos de dígitos
        # "1,000 000.00" → "1,000,000.00"
        # "177 446.35" → "177,446.35"
        monto_part = re.sub(r"(\d)\s+(\d)", r"\1,\2", monto_part)

        return prefijo + monto_part

    @staticmethod
    def _parsear_monto_ocr(monto_str: str) -> Decimal | None:
        """Parsea un monto que puede tener artefactos OCR residuales.

        Después de _normalizar_linea_ocr, la mayoría de errores ya
        están corregidos. Esta función maneja casos residuales:
        - Espacios que quedaron: "100 000.00"
        - Puntos como separador de miles: "9.178.00" (OCR confundió , con .)
        - Comas finales sueltas

        Returns:
            Decimal con el monto, o None si no se pudo parsear.
        """
        # Limpiar espacios
        cleaned = monto_str.replace(" ", "")

        # Si hay múltiples puntos, todos excepto el último son
        # separadores de miles (OCR confundió , con .)
        # Ejemplo: "9.178.00" → 9178.00
        dot_count = cleaned.count(".")
        if dot_count > 1:
            # Dejar solo el último punto como decimal
            parts = cleaned.rsplit(".", 1)
            cleaned = parts[0].replace(".", "") + "." + parts[1]

        # Quitar comas finales sueltas
        cleaned = cleaned.rstrip(",")

        return parse_money_safe(cleaned)

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
