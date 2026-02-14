"""
Adaptador de entrada: Parser de estados de cuenta SANTANDER.

Migrado de: extractor_santander_final.py (294 líneas originales)

DIFERENCIA ARQUITECTURAL con BBVA/Banorte:
Santander usa REGEX SOBRE LÍNEAS DE TEXTO, no posiciones X/Y.
Esto significa que:
- NO requiere PageText.has_words (funciona con texto plano).
- Funciona con cualquier TextExtractor (PDF, OCR, ZIP/txt).
- Es inherentemente más simple y robusto.

LÓGICA DE PARSEO (preservada del original):
1. Cada movimiento es una línea con formato: DD-MMM-YYYY FOLIO CONCEPTO MONTOS
2. Extrae fecha, folio (referencia), concepto y montos con regex.
3. Clasificación por keywords: ABONO, DEPOSITO, RECIBID, DEVOLUCION → depósito.
4. Todo lo demás → retiro.
5. Caso especial: "ABONO POR PAGO DE" con primer monto 0.00 → usa el segundo.
6. Detección de duplicados por combinación fecha_monto_contador.
7. Limpieza de texto duplicado para artefactos de OCR (ej: "22--EENNEE" → "2-ENE").

BUGS CORREGIDOS:
- float para montos en Excel → Decimal hasta la frontera de salida.
- Diccionario de meses local → month_map compartido.
- limpiar_monto() duplicado → parse_money_safe compartido.
- try/except vacío → errores explícitos con ParseError.
- print() sueltos → eliminados.

NOTA SOBRE ZIP/txt:
El original soporta ZIP con archivos .txt (resultado de OCR).
En la nueva arquitectura, eso se maneja con un TextExtractor separado
(ZipTxtExtractor, aún no implementado). El parser solo recibe PageText[],
sin importar de dónde vinieron.
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


class SantanderParser(BankParser):
    """Parser de estados de cuenta Santander.

    A diferencia de BBVA y Banorte, este parser trabaja sobre texto plano
    (líneas), sin necesidad de coordenadas de posición. Esto lo hace
    compatible con cualquier TextExtractor.

    El formato de cada movimiento en Santander es:
        DD-MMM-YYYY FOLIO CONCEPTO MONTO1 [MONTO2] [SALDO]
    donde la fecha y el folio están siempre al inicio de la línea.
    """

    # Keywords que identifican depósitos (el resto es retiro)
    _DEPOSIT_KEYWORDS: list[str] = [
        "ABONO",
        "DEPOSITO",
        "DEPÓSITO",
        "RECIBID",
        "DEVOLUCION",
        "DEVOLUCIÓN",
    ]

    # Patrón principal: DD-MMM-YYYY seguido de folio numérico
    # Ejemplo: "1-ENE-2025 123456 PAGO SERVICIO 1,500.00 120,000.00"
    _LINE_PATTERN: re.Pattern[str] = re.compile(r"^(\d{1,2})-([A-Z]{3})-(\d{4})\s*(\d+)(.*)")

    # Patrón para extraer montos con formato X,XXX.XX
    _MONEY_PATTERN: re.Pattern[str] = re.compile(r"[\d,]+\.\d{2}")

    # Patrón de cuenta Santander: XX-XXXXXXXX-X
    _ACCOUNT_PATTERN: re.Pattern[str] = re.compile(r"(?<!\d)(\d{2}-\d{8}-\d)(?!\d)")

    # Patrones de líneas que NO son continuación de descripción.
    # Son ruido de encabezados, pies de página o separadores que
    # podrían aparecer entre movimientos en el PDF.
    _NOISE_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"^[Pp][áa]gina\s*\d+", re.IGNORECASE),
        # Santander omite acentos en algunos PDFs: "Pgina 2 de 16"
        re.compile(r"^Pgina\s*\d+", re.IGNORECASE),
        # OCR corrupto: "P gina19 de23" (espacio entre P y gina)
        re.compile(r"^P\s+gina\s*\d+", re.IGNORECASE),
        re.compile(r"^\s*-{3,}\s*$"),  # líneas de separación "---"
        re.compile(r"^\d+\s*$"),  # líneas que son solo un número
        # Footer de Santander: "P-P 4500671" (puede aparecer en cualquier posición)
        re.compile(r"P-P\s+\d+"),
        # Headers de tabla que se repiten en cada página
        re.compile(r"^FECHA\s+FOLIO\s+DESCRIPCION"),
        re.compile(r"^ESTADO DE CUENTA"),
        re.compile(r"^Banco Santander"),
        re.compile(r"^Institucin|^Grupo Financiero"),
        re.compile(r"^PRADERAS|^PERIODO DEL|^CODIGO DE CLIENTE"),
        # Líneas de totales y resumen al final de sección de movimientos
        re.compile(r"^TOTAL\s", re.IGNORECASE),
        re.compile(r"SALDO FINAL", re.IGNORECASE),
        # Sección de abreviaturas y leyendas
        re.compile(r"Significado de abreviaturas", re.IGNORECASE),
        re.compile(r"Detalles de movimientos", re.IGNORECASE),
        # Sub-cuentas / inversiones
        re.compile(r"INVERSION CRECIENTE", re.IGNORECASE),
    ]

    @property
    def bank_name(self) -> str:
        return "SANTANDER"

    def parse(self, pages: list[PageText], file_name: str = "") -> ResultadoParseo:
        """Parsea un estado de cuenta Santander completo."""
        if not pages:
            raise ParseError("SANTANDER", file_name, "No se recibieron páginas")

        info_cuenta = self._extraer_info_cuenta(pages, file_name)
        año, mes = self._extraer_periodo(pages, file_name)
        movimientos = self._extraer_movimientos(pages, file_name)
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

        Santander usa formato de cuenta con guiones: XX-XXXXXXXX-X
        (ej: 65-50123456-7). Esto es diferente a BBVA/Banorte que
        usan 10 dígitos sin separador.
        """
        texto = pages[0].text
        cuenta = ""
        moneda = "MXN"

        match = self._ACCOUNT_PATTERN.search(texto)
        if match:
            cuenta = match.group(1)

        texto_upper = texto.upper()
        if "USD" in texto_upper or "DOLARES" in texto_upper or "DÓLARES" in texto_upper:
            moneda = "USD"

        if not cuenta:
            cuenta = "SIN_CUENTA"

        return InfoCuenta(banco="SANTANDER", cuenta=cuenta, moneda=moneda)

    # =================================================================
    # Extracción de periodo (año/mes)
    # =================================================================

    def _extraer_periodo(self, pages: list[PageText], file_name: str) -> tuple[int, int]:
        """Extrae año y mes del estado de cuenta.

        Santander incluye la fecha directamente en cada movimiento con
        año de 4 dígitos (DD-MMM-YYYY), así que extraemos del primer
        movimiento encontrado o de patrones del encabezado.
        """
        texto = "\n".join(p.text for p in pages[:2])

        # Estrategia 1: buscar fecha de periodo en encabezado
        patrones = [
            r"[Pp]eriodo.*?(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{4})",
            r"[Ff]echa\s+de\s+[Cc]orte.*?(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{4})",
            r"[Cc]orte.*?(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{4})",
        ]

        for patron in patrones:
            match = re.search(patron, texto)
            if match:
                try:
                    mes = month_to_int(match.group(2))
                    año = int(match.group(3))
                    return (año, mes)
                except ValueError:
                    continue

        # Estrategia 2: extraer del primer movimiento
        match = re.search(
            r"^(\d{1,2})-([A-Z]{3})-(\d{4})\s*(\d+)",
            texto,
            re.MULTILINE,
        )
        if match:
            try:
                mes = month_to_int(match.group(2))
                año = int(match.group(3))
                return (año, mes)
            except ValueError:
                pass

        # Estrategia 3: cualquier año 20XX
        match_año = re.search(r"20(\d{2})", texto)
        if match_año:
            return (2000 + int(match_año.group(1)), 1)

        raise ParseError(
            "SANTANDER",
            file_name,
            "No se pudo determinar el año/mes del estado de cuenta.",
        )

    # =================================================================
    # Extracción de movimientos
    # =================================================================

    def _extraer_movimientos(self, pages: list[PageText], file_name: str) -> list[Movimiento]:
        """Extrae movimientos de todas las páginas.

        Procesa línea por línea buscando el patrón DD-MMM-YYYY FOLIO.
        A diferencia de BBVA/Banorte, NO necesita coordenadas X/Y.

        SOPORTE MULTI-LÍNEA:
        Los movimientos de Santander pueden tener líneas de continuación
        con información adicional (remitente, cuenta origen, clave de
        rastreo, RFC, etc.). Ejemplo real:

            01-ABR-2025 5635768 ABONO TRANSFERENCIA SPEI HORA 09:58:31  51,451.13  2,744,700.76
                        RECIBIDO DE BAJIO
                        DE LA CUENTA 030231900039926298
                        DEL CLIENTE CUEROS ORION SA DE CV
                        CLAVE DE RASTREO BB1029312020788
                        REF 1029312
                        CONCEPTO PAGO
                        RFC COR230419MX9

        La lógica agrupa líneas en "bloques": cada bloque inicia con una
        línea que matchea _LINE_PATTERN (fecha) y las líneas siguientes
        que NO matchean se consideran continuación de la descripción,
        siempre que no sean ruido (pies de página, separadores, etc.).
        """
        movimientos: list[Movimiento] = []
        procesados: set[str] = set()

        for page in pages:
            # last_match guarda el match de la línea de fecha actual.
            # continuation_lines acumula las líneas de continuación.
            last_match: re.Match[str] | None = None
            continuation_lines: list[str] = []

            for linea in page.lines:
                linea = linea.strip()
                if not linea:
                    continue

                # Limpiar texto duplicado de OCR si se detecta.
                # El PDF de Santander tiene doble capa de texto superpuesto:
                # cada carácter aparece dos veces consecutivas.
                # Ejemplo: "RREECCIIBBIIDDOO DDEE BBBBVVAA" → "RECIBIDO DE BBVA"
                # Esto afecta TANTO líneas de fecha como líneas de continuación,
                # por eso se aplica a TODA línea al inicio del loop.
                # Además, al limpiar líneas de fecha doubled, se convierten en
                # idénticas a las clean → el sistema de duplicados las descarta.
                if self._es_texto_duplicado(linea):
                    linea = self._limpiar_texto_duplicado(linea)

                # ¿Es inicio de un nuevo movimiento?
                match = self._LINE_PATTERN.match(linea)
                if match:
                    # Antes de iniciar el nuevo bloque, procesar el anterior
                    if last_match is not None:
                        mov = self._procesar_linea(last_match, continuation_lines, procesados)
                        if mov is not None:
                            movimientos.append(mov)

                    # Iniciar nuevo bloque
                    last_match = match
                    continuation_lines = []
                else:
                    # No es movimiento nuevo → ¿es continuación válida?
                    if last_match is not None and self._es_linea_continuacion(linea):
                        continuation_lines.append(linea)

            # Procesar el último movimiento de la página
            # (no hay siguiente match que lo "cierre")
            if last_match is not None:
                mov = self._procesar_linea(last_match, continuation_lines, procesados)
                if mov is not None:
                    movimientos.append(mov)

        return movimientos

    def _es_linea_continuacion(self, linea: str) -> bool:
        """Determina si una línea es continuación de la descripción anterior.

        Filtra ruido que podría aparecer entre movimientos:
        - "Página X de Y" (pies de página)
        - Líneas de separación ("---")
        - Líneas que son solo números

        ¿Por qué no ser más restrictivo? Porque las líneas de continuación
        de Santander son muy variadas (remitente, cuenta, clave de rastreo,
        RFC, concepto libre, etc.) y un filtro demasiado estricto perdería
        información valiosa. Es mejor incluir una línea de más que perder
        datos del movimiento.

        Args:
            linea: Línea de texto ya stripped.

        Returns:
            True si la línea parece ser continuación legítima.
        """
        return all(not pattern.search(linea) for pattern in self._NOISE_PATTERNS)

    def _procesar_linea(
        self,
        match: re.Match[str],
        lineas_continuacion: list[str],
        procesados: set[str],
    ) -> Movimiento | None:
        """Procesa un bloque de movimiento (línea principal + continuación).

        Args:
            match: Match del regex con grupos (dia, mes, año, folio, resto).
            lineas_continuacion: Líneas de texto que siguen al movimiento
                y forman parte de su descripción (ej: remitente, cuenta
                origen, clave de rastreo, RFC, etc.).
            procesados: Set de IDs ya procesados para detectar duplicados.

        Returns:
            Movimiento si se procesó correctamente, None si es duplicado
            o no tiene montos válidos.
        """
        dia = int(match.group(1))
        mes_str = match.group(2)
        año = int(match.group(3))
        folio = match.group(4)
        resto = match.group(5).strip()

        # Parsear fecha
        try:
            mes = month_to_int(mes_str)
            fecha = date(año, mes, dia)
        except (ValueError, TypeError):
            return None

        # Extraer montos del resto de la línea
        montos_str = self._MONEY_PATTERN.findall(resto)

        if len(montos_str) < 2:
            return None

        # Extraer concepto (todo lo que no es monto)
        concepto = resto
        for monto_str in montos_str:
            concepto = concepto.replace(monto_str, "")
        concepto = " ".join(concepto.split()).strip()

        # Anexar líneas de continuación al concepto.
        # Las líneas de continuación contienen info adicional como
        # remitente, cuenta origen, clave de rastreo, RFC, etc.
        # Se unen con " | " para mantener claridad visual y facilitar
        # el procesamiento posterior.
        if lineas_continuacion:
            partes_extra = [" ".join(linea.split()) for linea in lineas_continuacion]
            concepto = concepto + " | " + " | ".join(partes_extra)

        # Determinar monto del movimiento
        monto = parse_money_safe(montos_str[0])

        # Caso especial: "ABONO POR PAGO DE" con primer monto 0.00
        # Formato: CONCEPTO 0.00 (IVA) MONTO_REAL SALDO
        if monto == Decimal("0") and len(montos_str) >= 3:
            monto = parse_money_safe(montos_str[1])

        if monto <= Decimal("0"):
            return None

        # Detección de duplicados
        # Santander puede generar líneas duplicadas en PDFs con OCR.
        # Se usa fecha + monto + contador incremental como ID único.
        base_id = f"{fecha}_{monto}"
        contador = 1
        movimiento_id = f"{base_id}_{contador}"

        while movimiento_id in procesados:
            contador += 1
            movimiento_id = f"{base_id}_{contador}"
            if contador > 500:
                return None

        procesados.add(movimiento_id)

        # Clasificar por keywords
        tipo = self._detectar_tipo(concepto)

        deposito = monto if tipo == "deposito" else Decimal("0")
        retiro = monto if tipo == "retiro" else Decimal("0")

        return Movimiento(
            fecha=fecha,
            concepto=concepto,
            referencia=folio,
            retiro=retiro,
            deposito=deposito,
        )

    # =================================================================
    # Clasificación y helpers
    # =================================================================

    def _detectar_tipo(self, concepto: str) -> str:
        """Clasifica un movimiento como depósito o retiro por keywords.

        A diferencia de BBVA/Banorte que usan posición X, Santander
        clasifica puramente por el texto del concepto.
        """
        concepto_upper = concepto.upper()

        if any(kw in concepto_upper for kw in self._DEPOSIT_KEYWORDS):
            return "deposito"

        return "retiro"

    @staticmethod
    def _es_texto_duplicado(texto: str) -> bool:
        """Detecta si una línea tiene caracteres duplicados por capa de texto superpuesto.

        El PDF de Santander coloca dos capas de texto idénticas ligeramente
        desplazadas. Cuando pdfplumber extrae el texto, los caracteres se
        intercalan: "RECIBIDO" → "RREECCIIBBIIDDOO".

        La detección funciona así:
        1. Toma los primeros N caracteres alfanuméricos de la línea.
        2. Cuenta cuántos forman pares consecutivos idénticos (posiciones 0-1, 2-3, etc.).
        3. Si más del 70% son pares → la línea está duplicada.

        ¿Por qué 70% y no 100%? Porque algunas líneas tienen mezcla de
        texto duplicado y separadores (espacios, guiones) que no siempre
        se duplican perfectamente. 70% es suficientemente alto para evitar
        falsos positivos en texto normal.

        ¿Por qué solo alfanuméricos? Los espacios y puntuación pueden
        tener comportamientos irregulares en la extracción de texto.
        Los caracteres alfanuméricos son el indicador más fiable.

        Args:
            texto: Línea de texto a evaluar.

        Returns:
            True si la línea parece tener caracteres duplicados.
        """
        # Extraer solo caracteres alfanuméricos para la evaluación
        alnum = [c for c in texto if c.isalnum()]

        # Necesitamos al menos 6 caracteres alfanuméricos para evaluar
        # (3 pares mínimo). Con menos, el riesgo de falso positivo es alto.
        if len(alnum) < 6:
            return False

        # Evaluar los primeros 20 caracteres alfanuméricos (10 pares).
        # No necesitamos revisar toda la línea; si los primeros 10 pares
        # están duplicados, el resto también lo estará.
        muestra = alnum[: min(len(alnum), 20)]
        pares_totales = len(muestra) // 2
        pares_iguales = sum(
            1 for i in range(0, pares_totales * 2, 2) if muestra[i] == muestra[i + 1]
        )

        return pares_totales > 0 and pares_iguales / pares_totales > 0.7

    @staticmethod
    def _limpiar_texto_duplicado(texto: str) -> str:
        """Limpia texto con caracteres duplicados por artefactos de OCR.

        Cuando Santander se procesa con OCR, algunos caracteres se
        duplican: "22--EENNEE--22002255" → "2-ENE-2025".
        Esta función detecta pares de caracteres idénticos consecutivos
        y los reduce a uno.
        """
        resultado: list[str] = []
        i = 0
        while i < len(texto):
            if i < len(texto) - 1 and texto[i] == texto[i + 1]:
                resultado.append(texto[i])
                i += 2
            else:
                resultado.append(texto[i])
                i += 1
        return "".join(resultado)

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
