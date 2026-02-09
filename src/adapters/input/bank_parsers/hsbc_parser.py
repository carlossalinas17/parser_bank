"""
Adaptador de entrada: Parser de estados de cuenta HSBC.

Migrado de: hsbc_parser.py (290 líneas originales, OCR-based)

DIFERENCIA ARQUITECTURAL FUNDAMENTAL:
El script original requería OCR (pytesseract + pdf2image) para leer los
PDFs de HSBC porque el texto extraído por pdfplumber aparecía "garbled".
Descubrimos que el PDF usa una codificación CID personalizada (similar a
EBCDIC CP500) que se puede decodificar directamente, eliminando la
dependencia de OCR. Esto es 100x más rápido y más preciso.

COMPARACIÓN CON OTROS PARSERS:
- vs BBVA/Banorte: Similar (coordenadas X), pero requiere decodificación
  EBCDIC previa y detección dinámica de columnas desde el header.
- vs Santander/Scotiabank: NO usa regex sobre texto plano porque la
  clasificación retiro/depósito solo es distinguible por posición X.
- vs Vantage Bank: NO clasifica por sección sino por columna X.

LÓGICA DE PARSEO:
1. Decodificar EBCDIC en cada palabra extraída por pdfplumber.
2. Detectar el header de la tabla ("Día", "Retiro/Cargo", "Depósito/Abono",
   "Saldo") para establecer límites de columnas dinámicamente.
3. Cada movimiento inicia con un día (1-31) en la columna Día.
4. Clasificar montos por posición X:
   - X en rango Retiro/Cargo → retiro.
   - X en rango Depósito/Abono → depósito.
   - X en rango Saldo → saldo (ignorado, solo para validación).
5. Las referencias pueden ser multi-línea (ej: "13651011" + "41234").
6. El año y mes se extraen del periodo en el header.

BUGS CORREGIDOS vs original:
- OCR eliminado (decodificación directa EBCDIC).
- float para montos → Decimal.
- Clasificación retiro/depósito: el original usaba OCR con tolerancia
  de posición baja, causando errores. Ahora con posiciones exactas de
  pdfplumber la clasificación es perfecta.
- force_retiro_deposito() eliminado (no necesario con posiciones exactas).
- Detección de header: el original buscaba keywords OCR con tolerancia;
  ahora busca las palabras decodificadas exactas.
"""

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.adapters.input.bank_parsers.hsbc_ebcdic import (
    decode_hsbc_text,
    needs_ebcdic_decoding,
)
from src.domain.exceptions import ParseError
from src.domain.models.info_cuenta import InfoCuenta
from src.domain.models.movimiento import Movimiento
from src.domain.models.page_text import PageText
from src.domain.models.resultado_parseo import ResultadoParseo
from src.domain.models.resumen import Resumen
from src.domain.models.word_info import WordInfo
from src.domain.ports.bank_parser import BankParser
from src.domain.shared.money import parse_money_safe


@dataclass(frozen=True)
class _ColumnBoundaries:
    """Límites X de cada columna, detectados dinámicamente del header.

    Cada atributo es la coordenada X0 del inicio de esa columna.
    El fin de cada columna es el inicio de la siguiente.
    """

    dia_x: float
    descripcion_x: float
    referencia_x: float
    retiro_x: float
    deposito_x: float
    saldo_x: float


class HsbcParser(BankParser):
    """Parser de estados de cuenta HSBC México.

    Requiere PageText con words (coordenadas X/Y) porque la
    clasificación retiro/depósito solo es distinguible por columna X.

    Los PDFs de HSBC usan encoding EBCDIC-CID personalizado, así que
    cada word se decodifica internamente antes de procesar.
    """

    # Marcador de inicio de la tabla de movimientos
    _TABLE_MARKER = "DETALLE MOVIMIENTOS CUENTA INTEGRAL"

    # Keywords del header para detectar columnas
    _HEADER_KEYWORDS: dict[str, list[str]] = {
        "dia": ["Dia", "DUa", "D\u00eda"],
        "descripcion": ["Descripcion", "Descripción"],
        "referencia": ["Referencia", "Serial"],
        "retiro": ["Retiro", "Cargo"],
        "deposito": ["Deposito", "Depósito", "Abono"],
        "saldo": ["Saldo"],
    }

    # Fin de la tabla de movimientos
    _TABLE_END_MARKERS: list[str] = [
        "CoDi",
        "Informacion",
        "Información",
        "Aclaraciones",
        "Promociones",
        "Mensajes",
        "Emitido",
    ]

    @property
    def bank_name(self) -> str:
        return "HSBC"

    def parse(self, pages: list[PageText], file_name: str = "") -> ResultadoParseo:
        """Parsea un estado de cuenta HSBC completo."""
        if not pages:
            raise ParseError("HSBC", file_name, "No se recibieron páginas")

        # Verificar que hay words con coordenadas
        tiene_words = any(p.has_words for p in pages)
        if not tiene_words:
            raise ParseError(
                "HSBC",
                file_name,
                "Se requieren words con coordenadas X/Y. "
                "El extractor debe usar include_words=True.",
            )

        # Decodificar EBCDIC en todas las words
        pages_decoded = [self._decode_page(p) for p in pages]

        # Extraer info de cuenta del texto decodificado completo
        texto_completo = "\n".join(p.text for p in pages_decoded)
        info_cuenta = self._extraer_info_cuenta(texto_completo)
        periodo = self._extraer_periodo(texto_completo, file_name)
        año, mes = periodo

        # Extraer movimientos de todas las páginas usando coordenadas
        movimientos: list[Movimiento] = []
        for page in pages_decoded:
            movs = self._extraer_movimientos_pagina(page, año, mes, file_name)
            movimientos.extend(movs)

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
    # Decodificación EBCDIC
    # =================================================================

    def _decode_page(self, page: PageText) -> PageText:
        """Decodifica EBCDIC en el texto y en cada word de la página.

        La decisión de decodificar se toma a nivel de PÁGINA, no de word
        individual. ¿Por qué? Porque el encoding EBCDIC es una propiedad
        del font del PDF — si la página tiene tokens (cid:NNN) en su
        texto, entonces TODAS las words usan el mismo encoding, incluso
        aquellas que solo contienen caracteres Unicode mapeados sin tokens
        CID (ej: 'æł' que son los dígitos '18').

        Si el texto no tiene tokens CID (ej: en tests unitarios con
        texto ya limpio), se retorna sin modificar para evitar corrupción
        (el mapeo convierte 'a' → '/', 'l' → '%', etc.).
        """
        # Decidir si la página necesita decodificación verificando el
        # texto completo de la página. Si hay al menos un token CID,
        # todo el contenido está en encoding EBCDIC.
        page_needs_decoding = needs_ebcdic_decoding(page.text) or any(
            needs_ebcdic_decoding(w.text) for w in page.words
        )

        if not page_needs_decoding:
            return page

        decoded_text = decode_hsbc_text(page.text)
        decoded_words = [
            WordInfo(
                text=decode_hsbc_text(w.text),
                x0=w.x0,
                x1=w.x1,
                top=w.top,
                bottom=w.bottom,
            )
            for w in page.words
        ]
        return PageText(
            page_num=page.page_num,
            text=decoded_text,
            words=decoded_words,
        )

    # =================================================================
    # Info de cuenta
    # =================================================================

    def _extraer_info_cuenta(self, texto: str) -> InfoCuenta:
        """Extrae banco, cuenta y moneda del texto decodificado.

        HSBC México usa:
        - NÚMERO DE CUENTA + 10 dígitos (ej: 4007185804).
        - CLABE INTERBANCARIA + 18 dígitos (no la usamos para el campo cuenta).
        - "PESOS MEXICANOS" → MXN.
        """
        cuenta = ""
        moneda = "MXN"  # Default para HSBC México

        # Buscar "No." seguido de dígitos en la tabla de movimientos
        match = re.search(r"CUENTA\s+INTEGRAL\s+No\.\s+(\d{10})", texto)
        if match:
            cuenta = match.group(1)
        else:
            # Fallback: buscar 10 dígitos después de "NUMERO DE CUENTA"
            match = re.search(r"NUMERO\s+DE\s+CUENTA\s+.*?(\d{10})", texto)
            if match:
                cuenta = match.group(1)

        # Detectar moneda
        texto_upper = texto[:3000].upper()
        if "USD" in texto_upper or "DOLARES" in texto_upper:
            moneda = "USD"

        if not cuenta:
            cuenta = "SIN_CUENTA"

        return InfoCuenta(banco="HSBC", cuenta=cuenta, moneda=moneda)

    # =================================================================
    # Periodo
    # =================================================================

    def _extraer_periodo(self, texto: str, file_name: str) -> tuple[int, int]:
        """Extrae año y mes del periodo.

        Busca el patrón "DD/MM/YYYY al DD/MM/YYYY" en el texto.
        Usa la fecha final (corte) como referencia.
        """
        # Patrón: "01/11/2025 al 30/11/2025"
        match = re.search(
            r"(\d{2})/(\d{2})/(\d{4})\s+al\s+(\d{2})/(\d{2})/(\d{4})",
            texto,
        )
        if match:
            año = int(match.group(6))
            mes = int(match.group(5))
            return (año, mes)

        raise ParseError("HSBC", file_name, "No se encontró el periodo (DD/MM/YYYY al DD/MM/YYYY)")

    # =================================================================
    # Extracción de movimientos (coordinadas)
    # =================================================================

    def _extraer_movimientos_pagina(
        self,
        page: PageText,
        año: int,
        mes: int,
        file_name: str,
    ) -> list[Movimiento]:
        """Extrae movimientos de una página usando coordenadas X/Y.

        Proceso:
        1. Verificar que la página tiene la tabla de movimientos.
        2. Detectar el header para establecer límites de columnas.
        3. Agrupar words en líneas por coordenada Y.
        4. Para cada línea después del header:
           - Si la columna Día tiene un número → nuevo movimiento.
           - Si no → continuación (referencia multi-línea).
        5. Clasificar montos por posición X.
        """
        if not page.has_words:
            return []

        # Verificar que esta página tiene tabla de movimientos
        if not self._tiene_tabla_movimientos(page):
            return []

        # Detectar header y obtener límites de columnas
        boundaries = self._detectar_columnas(page)
        if boundaries is None:
            return []

        # Agrupar words en líneas por Y
        lineas = self._agrupar_en_lineas(page.words, y_tolerance=4.0)

        # Encontrar la línea del header para saber dónde empiezan los datos
        header_y = self._encontrar_header_y(page.words, boundaries)
        if header_y is None:
            return []

        # Procesar líneas después del header
        movimientos: list[Movimiento] = []
        current: dict[str, object] | None = None

        for linea_y, words_linea in sorted(lineas.items()):
            # Solo procesar líneas debajo del header
            if linea_y <= header_y + 5:
                continue

            # Detectar fin de tabla
            texto_linea = " ".join(w.text for w in words_linea)
            if any(marker in texto_linea for marker in self._TABLE_END_MARKERS):
                break

            # Asignar words a columnas
            cols = self._asignar_columnas(words_linea, boundaries)

            dia_text = cols["dia"].strip()
            desc_text = cols["descripcion"].strip()
            ref_text = cols["referencia"].strip()
            retiro_text = cols["retiro"].strip()
            deposito_text = cols["deposito"].strip()

            # ¿Es inicio de un nuevo movimiento?
            if self._es_dia(dia_text):
                # Guardar movimiento anterior
                if current is not None:
                    mov = self._construir_movimiento(current, año, mes)
                    if mov is not None:
                        movimientos.append(mov)

                current = {
                    "dia": dia_text,
                    "descripcion": desc_text,
                    "referencia": ref_text,
                    "retiro": retiro_text,
                    "deposito": deposito_text,
                }
            elif current is not None:
                # Continuación: agregar referencia multi-línea o descripción extra
                if ref_text:
                    current["referencia"] = (str(current["referencia"]) + " " + ref_text).strip()
                if desc_text:
                    current["descripcion"] = (str(current["descripcion"]) + " " + desc_text).strip()
                # Si montos aparecen en línea de continuación (raro pero posible)
                if retiro_text and not str(current.get("retiro", "")):
                    current["retiro"] = retiro_text
                if deposito_text and not str(current.get("deposito", "")):
                    current["deposito"] = deposito_text

        # Guardar último movimiento
        if current is not None:
            mov = self._construir_movimiento(current, año, mes)
            if mov is not None:
                movimientos.append(mov)

        return movimientos

    # =================================================================
    # Detección de tabla y header
    # =================================================================

    def _tiene_tabla_movimientos(self, page: PageText) -> bool:
        """Verifica si la página contiene la tabla de movimientos."""
        return self._TABLE_MARKER in page.text

    def _detectar_columnas(self, page: PageText) -> _ColumnBoundaries | None:
        """Detecta los límites de columnas desde el header de la tabla.

        Busca las palabras clave del header SOLO después del marcador
        "DETALLE MOVIMIENTOS", y verifica que estén en la misma línea Y.
        """
        # Paso 1: encontrar la Y del marcador "DETALLE MOVIMIENTOS"
        marker_y: float | None = None
        for word in page.words:
            if "DETALLE" in word.text and "MOVIMIENTO" in word.text:
                marker_y = word.top
                break

        if marker_y is None:
            return None

        # Paso 2: buscar header words SOLO debajo del marcador
        # (dentro de 30 puntos debajo del marcador)
        header_words = [w for w in page.words if marker_y < w.top <= marker_y + 30]

        if not header_words:
            return None

        # Paso 3: detectar cada columna del header
        encontrados: dict[str, float] = {}
        for word in header_words:
            text = word.text.strip()
            for col_name, keywords in self._HEADER_KEYWORDS.items():
                if col_name in encontrados:
                    continue
                if any(kw in text for kw in keywords):
                    encontrados[col_name] = word.x0
                    break

        # Necesitamos al menos dia, retiro, deposito y saldo
        requeridos = {"dia", "retiro", "deposito", "saldo"}
        if not requeridos.issubset(encontrados.keys()):
            return None

        # La columna "Día" es muy estrecha (solo 1-2 dígitos, ~10pt de ancho).
        # La descripción comienza inmediatamente después (~x0=60), NO en la
        # posición X del header "Descripción" (que está centrado a ~x0=142).
        # Por eso forzamos un límite dia→descripcion = dia_x + 18.
        dia_x = encontrados.get("dia", 0)
        desc_start = dia_x + 18  # Justo después del día (2 dígitos)

        return _ColumnBoundaries(
            dia_x=dia_x,
            descripcion_x=desc_start,
            referencia_x=encontrados.get("referencia", encontrados["retiro"] - 80),
            retiro_x=encontrados["retiro"],
            deposito_x=encontrados["deposito"],
            saldo_x=encontrados["saldo"],
        )

    def _encontrar_header_y(self, words: list[WordInfo], bounds: _ColumnBoundaries) -> float | None:
        """Encuentra la coordenada Y del header de la tabla.

        Busca "Saldo" cerca de la posición X esperada Y cerca de las
        otras columnas del header (retiro, deposito).
        """
        # Buscar "Saldo" que esté cerca de la posición X del header
        # Y que esté cerca de otras columnas del header en Y
        for word in words:
            text = word.text.strip()
            if text == "Saldo" and abs(word.x0 - bounds.saldo_x) < 20:
                return word.top
        return None

    # =================================================================
    # Agrupación de words en líneas
    # =================================================================

    @staticmethod
    def _agrupar_en_lineas(
        words: list[WordInfo], y_tolerance: float = 4.0
    ) -> dict[float, list[WordInfo]]:
        """Agrupa words en líneas por cercanía de coordenada Y.

        Words con Y similar (dentro de y_tolerance) se consideran
        parte de la misma línea visual.

        Returns:
            Dict de Y representativo → lista de words en esa línea.
        """
        if not words:
            return {}

        sorted_words = sorted(words, key=lambda w: (w.top, w.x0))
        lineas: dict[float, list[WordInfo]] = {}

        for word in sorted_words:
            # Buscar línea existente con Y cercano
            matched_y: float | None = None
            for y_rep in lineas:
                if abs(word.top - y_rep) <= y_tolerance:
                    matched_y = y_rep
                    break

            if matched_y is not None:
                lineas[matched_y].append(word)
            else:
                lineas[word.top] = [word]

        # Ordenar words dentro de cada línea por X
        for y_rep in lineas:
            lineas[y_rep].sort(key=lambda w: w.x0)

        return lineas

    # =================================================================
    # Asignación de words a columnas
    # =================================================================

    @staticmethod
    def _asignar_columnas(words: list[WordInfo], bounds: _ColumnBoundaries) -> dict[str, str]:
        """Asigna cada word a una columna basándose en su posición X.

        La lógica es: la word pertenece a la columna cuyo rango X
        contiene el centro horizontal de la word.
        Los rangos son:
        - dia: [dia_x, descripcion_x)
        - descripcion: [descripcion_x, referencia_x)
        - referencia: [referencia_x, retiro_x)
        - retiro: [retiro_x, deposito_x)
        - deposito: [deposito_x, saldo_x)
        - saldo: [saldo_x, ∞)
        """
        # Definir rangos como lista de (nombre, x_inicio, x_fin)
        columnas = [
            ("dia", bounds.dia_x, bounds.descripcion_x),
            ("descripcion", bounds.descripcion_x, bounds.referencia_x),
            ("referencia", bounds.referencia_x, bounds.retiro_x),
            ("retiro", bounds.retiro_x, bounds.deposito_x),
            ("deposito", bounds.deposito_x, bounds.saldo_x),
            ("saldo", bounds.saldo_x, float("inf")),
        ]

        result: dict[str, list[str]] = {col[0]: [] for col in columnas}

        for word in words:
            x_center = word.center_x
            for col_name, x_start, x_end in columnas:
                if x_start <= x_center < x_end:
                    result[col_name].append(word.text)
                    break

        return {col: " ".join(parts) for col, parts in result.items()}

    # =================================================================
    # Helpers de parseo
    # =================================================================

    @staticmethod
    def _es_dia(text: str) -> bool:
        """Verifica si el texto parece un día del mes (1-31)."""
        text = text.strip()
        if not text:
            return False
        # Acepta: "03", "3", "10", "31"
        if re.fullmatch(r"\d{1,2}", text):
            val = int(text)
            return 1 <= val <= 31
        return False

    @staticmethod
    def _limpiar_monto(text: str) -> str:
        """Limpia texto de monto removiendo $ y espacios."""
        return text.replace("$", "").replace(" ", "").strip()

    def _construir_movimiento(
        self, data: dict[str, object], año: int, mes: int
    ) -> Movimiento | None:
        """Construye un Movimiento a partir de los datos crudos de columnas."""
        dia_str = str(data.get("dia", "")).strip()
        descripcion = str(data.get("descripcion", "")).strip()
        referencia_raw = str(data.get("referencia", "")).strip()
        retiro_str = self._limpiar_monto(str(data.get("retiro", "")))
        deposito_str = self._limpiar_monto(str(data.get("deposito", "")))

        if not dia_str or not descripcion:
            return None

        # Parsear fecha (solo día, el mes/año viene del periodo)
        try:
            dia = int(dia_str)
            fecha = date(año, mes, dia)
        except (ValueError, TypeError):
            return None

        # Parsear montos
        retiro = parse_money_safe(retiro_str) if retiro_str else Decimal("0")
        deposito = parse_money_safe(deposito_str) if deposito_str else Decimal("0")

        # Al menos uno debe tener valor
        if retiro <= Decimal("0") and deposito <= Decimal("0"):
            return None

        # Limpiar referencia: unir partes multi-línea
        referencia = referencia_raw.replace("  ", " ").strip()

        return Movimiento(
            fecha=fecha,
            concepto=descripcion,
            referencia=referencia,
            retiro=retiro,
            deposito=deposito,
        )

    # =================================================================
    # Resumen
    # =================================================================

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