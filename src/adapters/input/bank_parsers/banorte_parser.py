"""
Adaptador de entrada: Parser de estados de cuenta BANORTE.

Migrado de: extractor_banorte_final.py (380 líneas originales)

LÓGICA DE PARSEO (preservada del original):
1. Solo procesa páginas que contienen "DETALLE DE MOVIMIENTOS".
2. Agrupa palabras por coordenada Y redondeada a múltiplos de 2.
3. Detecta movimientos por líneas que empiezan con fecha DD-MMM-YY o DD/MM/YYYY.
4. Filtra líneas con "SALDO ANTERIOR".
5. Captura conceptos multi-línea leyendo líneas subsiguientes sin fecha.
6. Clasificación de montos:
   - Si hay 2 montos: [MONTO, SALDO] → clasifica por keywords del concepto.
   - Si hay 3+ montos: [DEPOSITO, RETIRO, SALDO] → clasifica por posición X.
7. Soporta montos negativos con signo trailing (ej: "29,536.44-").
8. Extrae referencia del concepto (REFERENCIA:, REF:, CVE RAST:).

BUGS CORREGIDOS:
- Año hardcodeado '2024' → Se extrae del texto del PDF.
- float para montos → Decimal (precisión monetaria).
- Diccionario de meses local → month_map compartido.
- limpiar_monto() duplicado → parse_money_safe compartido.
- print() sueltos → Eliminados.
- try/except vacío → Errores explícitos con ParseError.

COORDENADAS X (empíricas, del formato PDF de Banorte):
Las posiciones difieren de BBVA porque Banorte usa un layout diferente.
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
from src.domain.models.word_info import WordInfo
from src.domain.ports.bank_parser import BankParser
from src.domain.shared.money import parse_money_safe
from src.domain.shared.month_map import month_to_int


class BanorteParser(BankParser):
    """Parser de estados de cuenta Banorte.

    Al igual que BBVA, requiere palabras con coordenadas (PageText.has_words).
    Banorte usa un sistema híbrido de clasificación:
    - Cuando hay 2 montos en la línea (monto + saldo), se clasifica
      por keywords del concepto (DEPOSITO, SPEI RECIBIDO, etc.).
    - Cuando hay 3+ montos (depósito + retiro + saldo), se clasifica
      por posición X.
    """

    # --- Constantes de posición X (coordenadas empíricas de Banorte) ---
    X_DEPOSITO_MIN: float = 370.0
    X_DEPOSITO_MAX: float = 445.0
    X_RETIRO_MIN: float = 445.0
    X_RETIRO_MAX: float = 515.0
    X_SALDO_MIN: float = 515.0

    # --- Keywords que identifican depósitos (fallback para 2 montos) ---
    # Se usan SOLO cuando la posición X no es concluyente (fuera de
    # ambas columnas). Normalmente la posición X es suficiente.
    #
    # NOTA: "DEP." cubre "DEP.EFECTIVO" (abreviatura frecuente en Banorte).
    # "DEPOSITO" no lo cubre porque "DEP.EFECTIVO" no empieza con
    # "DEPOSITO" sino con "DEP.".
    _DEPOSIT_KEYWORDS: list[str] = [
        "DEPOSITO",
        "DEPÓSITO",
        "DEP.",
        "SPEI RECIBIDO",
        "ABONO",
        "INTERES",
        "INTERÉS",
        "LIQ.INT",
        "RENDIMIENTO",
        "COMPENSACION DESFASE",
    ]

    # --- Patrones de referencia dentro del concepto ---
    _REF_PATTERNS: list[str] = [
        r"REFERENCIA:\s*(\w+)",
        r"REF(?:\s+SERV\s+EMISOR)?:\s*(\w+)",
        r"CVE\s+RAST(?:REO)?:\s*(\w+)",
    ]

    # --- Marcador de sección de movimientos ---
    _MOVEMENTS_MARKER: str = "DETALLE DE MOVIMIENTOS"

    # --- Marcadores que DETIENEN la captura de concepto multi-línea ---
    # Banorte incluye al final de cada página un footer informativo con
    # teléfonos, URLs y datos del banco. Sin estos marcadores, el footer
    # se adhiere como continuación del último movimiento de cada página.
    #
    # También al final del documento hay secciones informativas como
    # "Cargos Objetados en el Periodo" e "Informe de Depósitos en efectivo"
    # que no pertenecen a ningún movimiento.
    #
    # Cada string se busca con `in` (contención) dentro del texto de la
    # línea siguiente, así que no necesitan ser el inicio exacto.
    _CONTINUATION_STOP_MARKERS: list[str] = [
        # --- Footer de página (aparece en TODAS las páginas) ---
        "Línea Directa",
        "Linea Directa",  # sin acento (variante OCR)
        "Ciudad de México",
        "Ciudad de Mexico",  # sin acento
        "www.banorte",
        "Banco Mercan",  # "Banco Mercantil" truncado por pdfplumber
        "800 DIRECTA",
        "Resto del pa",  # "Resto del país" — cortamos antes del acento
        # --- Secciones informativas al final del documento ---
        "Cargos Objetados",
        "Informe de Dep",  # "Informe de Depósitos en efectivo"
        "OTROS\u25bc",  # "OTROS▼" (triángulo Unicode)
        "OTROS▼",  # redundante pero explícito
        # --- Encabezados de tabla post-movimientos ---
        "Folio Fecha Tipo",
    ]

    @property
    def bank_name(self) -> str:
        return "BANORTE"

    def parse(self, pages: list[PageText], file_name: str = "") -> ResultadoParseo:
        """Parsea un estado de cuenta Banorte completo."""
        if not pages:
            raise ParseError("BANORTE", file_name, "No se recibieron páginas")

        if not pages[0].has_words:
            raise ParseError(
                "BANORTE",
                file_name,
                "Las páginas no incluyen palabras con coordenadas (words). "
                "Banorte requiere PdfplumberExtractor con include_words=True.",
            )

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

        Banorte tiene varios tipos de cuenta con patrones diferentes:
        - "CUENTA PRODUCTIVA ESPECIAL II 0123456789"
        - "No. de Cuenta: 0123456789"
        - "ENLACE NEGOCIOS BASICA 0123456789"
        """
        cuenta = ""
        moneda = "MXN"

        # Buscar en las primeras 3 páginas (Banorte a veces pone la info en la 2da)
        for page in pages[:3]:
            texto = page.text

            if not cuenta:
                patrones_cuenta = [
                    r"CUENTA\s+PRODUCTIVA\s+ESPECIAL\s+II?\s*(\d{10})",
                    r"No\.\s*de\s*Cuenta[:\s]+(\d{10,})",
                    r"CUENTA[^\d]*(\d{10})",
                    r"ENLACE\s+NEGOCIOS\s+BASICA\s+(\d{10})",
                ]

                for patron in patrones_cuenta:
                    match = re.search(patron, texto, re.IGNORECASE)
                    if match:
                        cuenta = match.group(1)
                        break

            # Detección de moneda
            texto_upper = texto.upper()
            if "DOLARES" in texto_upper or "DÓLARES" in texto_upper or "USD" in texto_upper:
                moneda = "USD"

            if cuenta:
                break

        if not cuenta:
            cuenta = "SIN_CUENTA"

        return InfoCuenta(banco="BANORTE", cuenta=cuenta, moneda=moneda)

    # =================================================================
    # Extracción de periodo (año/mes)
    # =================================================================

    def _extraer_periodo(self, pages: list[PageText], file_name: str) -> tuple[int, int]:
        """Extrae año y mes del estado de cuenta.

        Busca patrones como:
        - "Periodo Del DD/MMM/YYYY Al DD/MMM/YYYY"
        - "Periodo Del DD-MMM-YY Al DD-MMM-YY"
        - Cualquier año 20XX en el texto.
        """
        texto = "\n".join(p.text for p in pages[:2])

        # Estrategia 1: "Periodo Del DD/MMM/YYYY" o similar
        patrones_periodo = [
            r"[Pp]eriodo\s+[Dd]el\s+\d{2}/\w+/(\d{4})",
            r"[Pp]eriodo\s+[Dd]el\s+\d{2}-([A-Za-z]{3})-(\d{2})\s+",
            r"[Ff]echa\s+de\s+[Cc]orte[:\s]+\d{1,2}[/\s-]([A-Za-z]{3,})[/\s-](\d{4})",
        ]

        # Patrón 1: extrae año de 4 dígitos directamente
        match = re.search(patrones_periodo[0], texto)
        if match:
            año = int(match.group(1))
            # Intentar extraer mes
            match_completo = re.search(r"[Pp]eriodo\s+[Dd]el\s+\d{2}/([A-Za-z]+)/\d{4}", texto)
            if match_completo:
                try:
                    mes = month_to_int(match_completo.group(1))
                    return (año, mes)
                except ValueError:
                    pass
            return (año, 1)

        # Patrón 2: fecha con año de 2 dígitos (DD-MMM-YY)
        match = re.search(r"[Pp]eriodo\s+[Dd]el\s+\d{2}-([A-Za-z]{3})-(\d{2})", texto)
        if match:
            try:
                mes = month_to_int(match.group(1))
                año_corto = int(match.group(2))
                año = 2000 + año_corto if año_corto < 50 else 1900 + año_corto
                return (año, mes)
            except ValueError:
                pass

        # Estrategia 2: cualquier año 20XX en el texto
        match_año = re.search(r"20(\d{2})", texto)
        if match_año:
            año = 2000 + int(match_año.group(1))
            # Intentar extraer mes de la primera fecha encontrada
            match_fecha = re.search(r"\d{2}-([A-Za-z]{3})-\d{2}", texto)
            if match_fecha:
                try:
                    mes = month_to_int(match_fecha.group(1))
                    return (año, mes)
                except ValueError:
                    pass
            return (año, 1)

        raise ParseError(
            "BANORTE",
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

        DIFERENCIA CLAVE con BBVA: Banorte solo procesa páginas que
        contienen el marcador "DETALLE DE MOVIMIENTOS". Las demás páginas
        (carátula, resumen, avisos) se ignoran.
        """
        movimientos: list[Movimiento] = []

        for page in pages:
            if not page.has_words:
                continue

            # Solo procesar páginas con la sección de movimientos
            if self._MOVEMENTS_MARKER not in page.text.upper():
                continue

            movs_pagina = self._procesar_pagina(page, año, file_name)
            movimientos.extend(movs_pagina)

        return movimientos

    def _procesar_pagina(self, page: PageText, año: int, file_name: str) -> list[Movimiento]:
        """Procesa una página individual.

        DIFERENCIA con BBVA en la agrupación Y:
        BBVA redondea a 1 decimal: round(top, 1)
        Banorte redondea a múltiplos de 2: round(top/2) * 2
        Esto es porque Banorte tiene un interlineado más variable.
        """
        # Agrupar palabras por línea (Y redondeada a múltiplos de 2)
        lineas_por_y: dict[float, list[WordInfo]] = {}
        for word in page.words:
            y = float(round(word.top / 2) * 2)
            if y not in lineas_por_y:
                lineas_por_y[y] = []
            lineas_por_y[y].append(word)

        ys_ordenados = sorted(lineas_por_y.keys())
        movimientos: list[Movimiento] = []

        # Patrón de fecha: DD-MMM-YY o DD/MM/YYYY
        patron_fecha = re.compile(r"^(\d{2}-[A-Z]{3}-\d{2}|\d{2}/\d{2}/\d{4})")

        i = 0
        while i < len(ys_ordenados):
            y = ys_ordenados[i]
            palabras_linea = sorted(lineas_por_y[y], key=lambda p: p.x0)
            texto_linea = " ".join(p.text for p in palabras_linea)

            # ¿Empieza con fecha?
            match_fecha = patron_fecha.match(texto_linea)
            if not match_fecha:
                i += 1
                continue

            fecha_str = match_fecha.group(1)

            # Filtrar SALDO ANTERIOR
            if "SALDO ANTERIOR" in texto_linea.upper():
                i += 1
                continue

            # Capturar líneas de continuación (concepto multi-línea)
            #
            # Banorte tiene conceptos que ocupan 2 o más líneas. Ejemplo:
            #   05-OCT-24  SPEI RECIBIDO DE EMPRESA
            #              REFERENCIA: ABC123 CVE RAST: XYZ789
            #
            # Se leen todas las líneas siguientes que NO empiecen con fecha
            # y NO sean footer/trailer del PDF.
            #
            # CONDICIONES DE PARADA (cualquiera detiene la captura):
            # 1. Línea que empieza con fecha → es otro movimiento
            # 2. Línea que contiene un marcador de footer/trailer
            #    (teléfonos del banco, URLs, secciones informativas)
            todas_palabras = list(palabras_linea)
            j = i + 1
            while j < len(ys_ordenados):
                y_siguiente = ys_ordenados[j]
                palabras_siguiente = sorted(lineas_por_y[y_siguiente], key=lambda p: p.x0)
                texto_siguiente = " ".join(p.text for p in palabras_siguiente)

                # Parada 1: Si empieza con fecha → otro movimiento
                if patron_fecha.match(texto_siguiente):
                    break

                # Parada 2: Si contiene un marcador de footer/trailer
                # del PDF → ya no es parte de ningún concepto.
                # Ejemplo: "Línea Directa para su empresa: Ciudad de
                # México: (55) 5140 5640..." aparece al pie de cada
                # página y NO pertenece al último movimiento.
                if self._es_linea_no_concepto(texto_siguiente):
                    break

                todas_palabras.extend(palabras_siguiente)
                j += 1

            # Procesar palabras: separar concepto de montos
            concepto_partes: list[str] = []
            montos_encontrados: list[tuple[float, Decimal, bool]] = []

            for palabra in todas_palabras:
                texto_palabra = palabra.text.strip()
                x_pos = palabra.x0

                # ¿Es monto con signo negativo trailing? (ej: "29,536.44-")
                match_negativo = re.match(r"^(\d{1,3}(?:,\d{3})*\.\d{2})-$", texto_palabra)
                match_normal = re.match(r"^\d{1,3}(?:,\d{3})*\.\d{2}$", texto_palabra)

                if match_negativo or match_normal:
                    texto_limpio = texto_palabra.replace("-", "")
                    monto = parse_money_safe(texto_limpio)
                    if monto > Decimal("0"):
                        es_negativo = match_negativo is not None
                        montos_encontrados.append((x_pos, monto, es_negativo))
                else:
                    # No es monto → agregar al concepto (excepto la fecha)
                    if texto_palabra not in fecha_str:
                        concepto_partes.append(texto_palabra)

            # Limpiar concepto
            concepto = " ".join(concepto_partes).strip()
            concepto = re.sub(r"^\d{2}-[A-Z]{3}-\d{2}", "", concepto).strip()

            # Extraer referencia del concepto
            referencia = self._extraer_referencia(concepto)

            # Clasificar montos
            deposito, retiro = self._clasificar_montos(montos_encontrados, concepto)

            i += 1

            # Solo crear movimiento si tiene monto positivo
            # (los montos negativos se clampan a 0 en el Movimiento)
            if deposito <= Decimal("0") and retiro <= Decimal("0"):
                continue

            # Construir fecha
            try:
                fecha = self._parsear_fecha(fecha_str, año)
            except ValueError:
                continue

            movimientos.append(
                Movimiento(
                    fecha=fecha,
                    concepto=concepto,
                    referencia=referencia,
                    retiro=retiro if retiro > Decimal("0") else Decimal("0"),
                    deposito=deposito if deposito > Decimal("0") else Decimal("0"),
                )
            )

        return movimientos

    # =================================================================
    # Clasificación de montos (lógica específica de Banorte)
    # =================================================================

    def _clasificar_montos(
        self,
        montos_encontrados: list[tuple[float, Decimal, bool]],
        concepto: str,
    ) -> tuple[Decimal, Decimal]:
        """Clasifica los montos como depósito o retiro.

        Lógica de clasificación:
        - 2 montos: [MONTO, SALDO] → se usa posición X del monto.
          La coordenada X indica en qué columna física está el número:
            - x0 en rango [370, 445) → columna DEPOSITO
            - x0 en rango [445, 515) → columna RETIRO
          Solo si X no es concluyente se usa el concepto (keywords).

        - 3+ montos: [DEPOSITO, RETIRO, SALDO] → se usa posición X.
          El último monto se ignora (es el saldo).

        ¿Por qué X primero y keywords después?
        Porque la posición X es la columna física del PDF — es
        determinista. Los keywords son heurísticos y fallan con
        abreviaturas ("DEP.EFECTIVO" ≠ "DEPOSITO") o conceptos
        atípicos ("SPEI 01042025 COMPENSACION..." ≠ "SPEI RECIBIDO").

        Args:
            montos_encontrados: Lista de (x_pos, monto, es_negativo).
            concepto: Texto del concepto para clasificación por keywords.

        Returns:
            Tupla (deposito, retiro) como Decimal.
        """
        deposito = Decimal("0")
        retiro = Decimal("0")

        if len(montos_encontrados) == 2:
            # Formato: [MONTO, SALDO]
            x_pos, monto, es_negativo = montos_encontrados[0]

            if es_negativo:
                monto = -monto

            # PRIMERO: clasificar por posición X (más confiable).
            # La coordenada X indica sin ambigüedad en qué columna
            # física del PDF está el monto. Ejemplo del PDF real:
            #   DEP.EFECTIVO → x0=389.6 (columna depósito)
            #   CHEQUE PAGADO → x0=463.1 (columna retiro)
            if self.X_DEPOSITO_MIN <= x_pos < self.X_DEPOSITO_MAX:
                deposito = monto
            elif self.X_RETIRO_MIN <= x_pos < self.X_RETIRO_MAX:
                retiro = monto
            else:
                # FALLBACK: posición X fuera de ambos rangos →
                # clasificar por keywords del concepto.
                concepto_upper = concepto.upper()
                es_deposito = (
                    any(
                        concepto_upper.startswith(kw)
                        for kw in self._DEPOSIT_KEYWORDS
                    )
                    or "SPEI RECIBIDO" in concepto_upper
                )

                if es_deposito:
                    deposito = monto
                else:
                    retiro = monto

        elif len(montos_encontrados) >= 3:
            # Formato: [DEPOSITO, RETIRO, SALDO] — clasificar por posición X
            # Ignorar el último monto (saldo)
            for x_pos, monto, es_negativo in montos_encontrados[:-1]:
                if es_negativo:
                    monto = -monto

                if self.X_DEPOSITO_MIN <= x_pos < self.X_DEPOSITO_MAX:
                    if deposito == Decimal("0"):
                        deposito = monto
                elif (
                    self.X_RETIRO_MIN <= x_pos < self.X_RETIRO_MAX
                    and retiro == Decimal("0")
                ):
                    retiro = monto

        return (deposito, retiro)

    # =================================================================
    # Helpers
    # =================================================================

    def _es_linea_no_concepto(self, texto: str) -> bool:
        """Determina si una línea es footer/trailer y NO parte de un concepto.

        Se usa durante la captura de líneas de continuación para detener
        la recolección cuando encontramos texto que NO pertenece a ningún
        movimiento bancario.

        ¿Por qué no simplemente filtrar después?
        Porque una vez que el texto del footer se mezcla con el concepto,
        es muy difícil separarlo limpiamente. Es mejor detectarlo ANTES
        de agregarlo. El footer incluye teléfonos, URLs y caracteres
        especiales que no aparecen en conceptos legítimos de Banorte.

        Args:
            texto: Texto completo de la línea candidata a continuación.

        Returns:
            True si la línea es footer/trailer (NO es concepto).
            False si la línea podría ser parte de un concepto.
        """
        texto_upper = texto.upper()
        return any(
            marcador.upper() in texto_upper
            for marcador in self._CONTINUATION_STOP_MARKERS
        )

    def _parsear_fecha(self, fecha_str: str, año_default: int) -> date:
        """Convierte string de fecha a date.

        Formatos soportados:
        - DD-MMM-YY (05-OCT-24) → usa el año del string
        - DD/MM/YYYY (05/10/2024) → usa el año del string

        Args:
            fecha_str: String de fecha.
            año_default: Año a usar si no se puede extraer del string.
        """
        # Formato DD-MMM-YY
        match = re.match(r"(\d{2})-([A-Z]{3})-(\d{2})", fecha_str)
        if match:
            dia = int(match.group(1))
            mes = month_to_int(match.group(2))
            año_corto = int(match.group(3))
            año = 2000 + año_corto if año_corto < 50 else 1900 + año_corto
            return date(año, mes, dia)

        # Formato DD/MM/YYYY
        match = re.match(r"(\d{2})/(\d{2})/(\d{4})", fecha_str)
        if match:
            dia = int(match.group(1))
            mes = int(match.group(2))
            año = int(match.group(3))
            return date(año, mes, dia)

        raise ValueError(f"Formato de fecha no reconocido: {fecha_str}")

    @staticmethod
    def _extraer_referencia(concepto: str) -> str:
        """Extrae la referencia del concepto.

        Banorte incluye la referencia DENTRO del texto del concepto,
        con diferentes formatos:
        - "REFERENCIA: ABC123"
        - "REF: ABC123"
        - "REF SERV EMISOR: ABC123"
        - "CVE RAST: ABC123" o "CVE RASTREO: ABC123"
        """
        patrones = [
            r"REFERENCIA:\s*(\w+)",
            r"REF(?:\s+SERV\s+EMISOR)?:\s*(\w+)",
            r"CVE\s+RAST(?:REO)?:\s*(\w+)",
        ]

        for patron in patrones:
            match = re.search(patron, concepto, re.IGNORECASE)
            if match:
                return match.group(1)

        return ""

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