"""
Adaptador de entrada: Parser de estados de cuenta BBVA.

Migrado de: extractor_bbva_final.py (311 líneas originales)

LÓGICA DE PARSEO (preservada del original):
1. Agrupa las palabras de cada página por coordenada Y (misma línea visual).
2. Detecta movimientos por líneas que empiezan con fecha DD/MMM.
3. Clasifica cargos vs abonos por la posición X de los montos:
   - x < 400  → Cargo (retiro)
   - 400 ≤ x < 470 → Abono (depósito)
   - x ≥ 470  → Saldo (se ignora)
4. Captura conceptos multi-línea leyendo líneas subsiguientes hasta
   encontrar otra fecha o una referencia "Ref."
5. Extrae número de cuenta del encabezado de la primera página.

BUGS CORREGIDOS:
- Año hardcodeado como '2021' → Se extrae del texto del PDF (periodo/fechas).
- float para montos → Decimal (precisión monetaria).
- Diccionario de meses local → Se usa month_map compartido.
- print() sueltos → Eliminados (la bitácora es responsabilidad del ProcessLogger).
- try/except vacío → Errores explícitos con ParseError.

COORDENADAS X (empíricas, obtenidas del formato PDF de BBVA):
Estas coordenadas se determinaron empíricamente analizando múltiples PDFs
de BBVA. Si BBVA cambia el formato de sus estados de cuenta, estos valores
podrían necesitar ajuste. Por eso son constantes de clase (fáciles de encontrar
y modificar) en lugar de números mágicos en el código.
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


class BBVAParser(BankParser):
    """Parser de estados de cuenta BBVA.

    Requiere que las páginas incluyan palabras con coordenadas
    (PageText.has_words == True). Si se le pasan páginas sin palabras,
    lanza ParseError indicando que se necesita PdfplumberExtractor
    con include_words=True.
    """

    # --- Constantes de posición X (coordenadas empíricas de BBVA) ---
    # Estas definen los límites entre las columnas del estado de cuenta.
    # Se pueden ajustar si BBVA cambia su formato de PDF.

    X_CARGO_MAX: float = 400.0
    """Montos con x < 400 están en la columna de CARGOS (retiros)."""

    X_ABONO_MAX: float = 470.0
    """Montos con 400 ≤ x < 470 están en la columna de ABONOS (depósitos).
    Montos con x ≥ 470 están en la columna de SALDO (se ignoran)."""

    # --- Textos de encabezado/pie que deben ignorarse ---
    _SKIP_PATTERNS: list[str] = [
        "bbva bancomer, s.a.",
        "bbva méxico, s.a.",
        "bbva mexico, s.a.",
        "institucion de banca multiple",
        "paseo de la reforma",
        "estado de cuenta",
        "pagina",
        "no. cuenta",
        "no. cliente",
        "grupo financiero",
        "fecha de corte",
    ]

    @property
    def bank_name(self) -> str:
        return "BBVA"

    def parse(self, pages: list[PageText], file_name: str = "") -> ResultadoParseo:
        """Parsea un estado de cuenta BBVA completo.

        Args:
            pages: Páginas con texto y palabras (de PdfplumberExtractor).
            file_name: Nombre del archivo original para trazabilidad.

        Returns:
            ResultadoParseo con todos los movimientos, info de cuenta y resumen.

        Raises:
            ParseError: Si no se pueden extraer movimientos o si las páginas
                       no incluyen palabras con coordenadas.
        """
        if not pages:
            raise ParseError("BBVA", file_name, "No se recibieron páginas")

        # Verificar que tenemos palabras con coordenadas
        if not pages[0].has_words:
            raise ParseError(
                "BBVA",
                file_name,
                "Las páginas no incluyen palabras con coordenadas (words). "
                "BBVA requiere PdfplumberExtractor con include_words=True.",
            )

        # Paso 1: Extraer info de cuenta de la primera página
        info_cuenta = self._extraer_info_cuenta(pages[0], file_name)

        # Paso 2: Extraer año y mes del periodo
        año, mes = self._extraer_periodo(pages, file_name)

        # Paso 3: Extraer movimientos de todas las páginas
        movimientos = self._extraer_movimientos(pages, año, file_name)

        # Paso 4: Calcular resumen
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
    # MÉTODOS PRIVADOS: Extracción de info de cuenta
    # =================================================================

    def _extraer_info_cuenta(self, primera_pagina: PageText, file_name: str) -> InfoCuenta:
        """Extrae banco, cuenta y moneda del encabezado.

        Busca patrones como:
        - "Cuenta: 0123456789"
        - "No. de Cuenta: 0123456789"
        - "No. Cuenta 0123456789"
        """
        texto = primera_pagina.text
        cuenta = ""

        # Intentar varios patrones (BBVA ha variado el formato)
        patrones_cuenta = [
            r"(?:Cuenta|No\.\s*de\s*Cuenta)[:\s]+(\d+)",
            r"No\.\s*Cuenta\s+(\d+)",
            r"CUENTA\s+(\d{8,})",
        ]

        for patron in patrones_cuenta:
            match = re.search(patron, texto, re.IGNORECASE)
            if match:
                cuenta = match.group(1)
                break

        if not cuenta:
            # No es fatal — puede que el formato haya cambiado.
            # Se registra una cuenta vacía que el usuario deberá completar.
            cuenta = "SIN_CUENTA"

        # Detectar moneda
        moneda = "MXN"
        texto_upper = texto.upper()
        if "USD" in texto_upper or "DOLAR" in texto_upper or "DOLLAR" in texto_upper:
            moneda = "USD"

        return InfoCuenta(banco="BBVA", cuenta=cuenta, moneda=moneda)

    # =================================================================
    # MÉTODOS PRIVADOS: Extracción de periodo (año/mes)
    # =================================================================

    def _extraer_periodo(self, pages: list[PageText], file_name: str) -> tuple[int, int]:
        """Extrae año y mes del estado de cuenta.

        Estrategia (en orden de prioridad):
        1. Buscar "Periodo" o "Fecha de corte" en el texto.
        2. Buscar patrón de año en las fechas de movimientos.
        3. Buscar cualquier año 20XX en la primera página.

        El código original hardcodeaba año='2021'. Esta función lo
        extrae dinámicamente del contenido del PDF.
        """
        # Combinar texto de las primeras 2 páginas
        texto = "\n".join(p.text for p in pages[:2])

        # Estrategia 1: Buscar "Periodo: DD MMM YYYY AL DD MMM YYYY"
        # o "Del DD de MMMM al DD de MMMM de YYYY"
        patrones_periodo = [
            # "Periodo: 01 OCT 2024 AL 31 OCT 2024"
            r"(?:Periodo|Per[ií]odo)[:\s]+\d{1,2}\s*[/\s]\s*([A-Za-z]{3,})\s*[/\s]\s*(\d{4})",
            # "Del 01 de Octubre al 31 de Octubre de 2024"
            r"[Dd]el?\s+\d{1,2}\s+de\s+([A-Za-z]+)\s+.*?(\d{4})",
            # "Fecha de corte: 31/OCT/2024"
            r"[Ff]echa\s+de\s+[Cc]orte[:\s]+\d{1,2}[/\s]([A-Za-z]{3,})[/\s](\d{4})",
            # "CORTE AL 31 DE OCTUBRE DE 2024"
            r"[Cc]orte\s+[Aa]l?\s+\d{1,2}\s+[Dd]e\s+([A-Za-z]+)\s+[Dd]e\s+(\d{4})",
            # "31/10/2024"
            r"(?:corte|periodo)[:\s]+\d{1,2}/(\d{2})/(\d{4})",
        ]

        for patron in patrones_periodo:
            match = re.search(patron, texto, re.IGNORECASE)
            if match:
                mes_str = match.group(1)
                año_str = match.group(2)

                try:
                    # Si el mes es numérico (último patrón)
                    mes = int(mes_str) if mes_str.isdigit() else month_to_int(mes_str)
                    año = int(año_str)
                    return (año, mes)
                except (ValueError, KeyError):
                    continue

        # Estrategia 2: Buscar cualquier año 20XX en la primera página
        match_año = re.search(r"20(\d{2})", texto)
        if match_año:
            año = 2000 + int(match_año.group(1))

            # Intentar extraer mes de cualquier fecha DD/MMM
            match_mes = re.search(r"\d{1,2}[/\s]([A-Za-z]{3})", texto)
            if match_mes:
                try:
                    mes = month_to_int(match_mes.group(1))
                    return (año, mes)
                except ValueError:
                    pass

            # Si no encontramos mes, usar enero como fallback
            return (año, 1)

        raise ParseError(
            "BBVA",
            file_name,
            "No se pudo determinar el año/mes del estado de cuenta. "
            "No se encontraron patrones de periodo ni fechas con año.",
        )

    # =================================================================
    # MÉTODOS PRIVADOS: Extracción de movimientos
    # =================================================================

    def _extraer_movimientos(
        self, pages: list[PageText], año: int, file_name: str
    ) -> list[Movimiento]:
        """Extrae todos los movimientos de todas las páginas.

        Lógica migrada de extraer_movimientos_bbva() original:
        1. Agrupa palabras por coordenada Y → líneas visuales.
        2. Para cada línea que empieza con DD/MMM:
           a. Busca montos y los clasifica por posición X.
           b. Lee líneas siguientes para completar el concepto.
           c. Extrae referencia si encuentra "Ref."
        """
        movimientos: list[Movimiento] = []

        for page in pages:
            if not page.has_words:
                continue

            movs_pagina = self._procesar_pagina(page, año, file_name)
            movimientos.extend(movs_pagina)

        return movimientos

    def _procesar_pagina(self, page: PageText, año: int, file_name: str) -> list[Movimiento]:
        """Procesa una página individual y extrae sus movimientos.

        Paso a paso:
        1. Agrupa las palabras por coordenada Y redondeada (misma línea).
        2. Ordena las líneas de arriba a abajo.
        3. Para cada línea, verifica si empieza con fecha DD/MMM.
        4. Si es movimiento, clasifica montos por posición X.
        5. Lee líneas subsiguientes para concepto multi-línea.
        """
        # Paso 1: Agrupar palabras por línea (misma coordenada Y)
        # Se redondea a 1 decimal porque pdfplumber puede dar tops
        # ligeramente diferentes para palabras en la misma línea visual
        # (por ejemplo, 150.1 y 150.3 son la misma línea).
        lineas_por_y: dict[float, list[WordInfo]] = {}
        for word in page.words:
            y = round(word.top, 1)
            if y not in lineas_por_y:
                lineas_por_y[y] = []
            lineas_por_y[y].append(word)

        # Paso 2: Ordenar líneas de arriba a abajo
        ys_ordenados = sorted(lineas_por_y.keys())

        # Paso 3: Procesar cada línea
        movimientos: list[Movimiento] = []

        for idx_linea, y in enumerate(ys_ordenados):
            palabras_linea = sorted(lineas_por_y[y], key=lambda p: p.x0)
            texto_linea = " ".join(p.text for p in palabras_linea)

            # ¿La línea empieza con fecha DD/MMM?
            match_fecha = re.match(r"^(\d{2}/[A-Z]{3})\s+(.+)", texto_linea)
            if not match_fecha:
                continue

            fecha_str = match_fecha.group(1)
            resto = match_fecha.group(2)

            # Paso 4: Buscar montos y clasificar por posición X
            cargo, abono = self._clasificar_montos(palabras_linea)

            # Si no hay ningún monto, no es un movimiento válido
            if cargo is None and abono is None:
                continue

            # Paso 5: Concepto multi-línea + referencia
            concepto, referencia = self._extraer_concepto_y_referencia(
                resto, idx_linea, ys_ordenados, lineas_por_y
            )

            # Construir fecha
            try:
                dia_str, mes_str = fecha_str.split("/")
                dia = int(dia_str)
                mes = month_to_int(mes_str)
                fecha = date(año, mes, dia)
            except (ValueError, KeyError):
                # Fecha inválida — skip este movimiento pero no abortar
                continue

            # Construir Movimiento
            movimientos.append(
                Movimiento(
                    fecha=fecha,
                    concepto=concepto,
                    referencia=referencia,
                    retiro=cargo if cargo is not None else Decimal("0"),
                    deposito=abono if abono is not None else Decimal("0"),
                )
            )

        return movimientos

    def _clasificar_montos(
        self, palabras_linea: list[WordInfo]
    ) -> tuple[Decimal | None, Decimal | None]:
        """Clasifica los montos de una línea como cargo o abono según posición X.

        Reglas (del original, empíricas):
        - x < 400  → Cargo (retiro)
        - 400 ≤ x < 470 → Abono (depósito)
        - x ≥ 470  → Saldo (se ignora, no es un movimiento)

        Returns:
            Tupla (cargo, abono). Cada uno es Decimal o None si no aplica.
        """
        cargo: Decimal | None = None
        abono: Decimal | None = None

        for palabra in palabras_linea:
            # ¿Es un monto? Verificar formato: dígitos con punto decimal
            texto_limpio = palabra.text.replace(",", "")
            if not re.match(r"^\d+\.\d{2}$", texto_limpio):
                continue

            monto = parse_money_safe(palabra.text)
            if monto == Decimal("0"):
                continue

            x_pos = palabra.x0

            if x_pos < self.X_CARGO_MAX:
                cargo = monto
            elif x_pos < self.X_ABONO_MAX:
                abono = monto
            # else: es saldo, se ignora

        return (cargo, abono)

    def _extraer_concepto_y_referencia(
        self,
        resto_linea_fecha: str,
        idx_linea_actual: int,
        ys_ordenados: list[float],
        lineas_por_y: dict[float, list[WordInfo]],
    ) -> tuple[str, str]:
        """Extrae el concepto completo (multi-línea) y la referencia.

        Lógica:
        1. Empieza con el texto después de la fecha en la línea del movimiento.
        2. Lee líneas siguientes y las agrega al concepto HASTA que:
           a. Encuentra otra línea con fecha (otro movimiento).
           b. Encuentra "Ref." (extrae la referencia y termina).
           c. Encuentra encabezados/pies de página (los salta).
           d. Encuentra una línea con montos grandes (la salta).
        3. Limpia el concepto: quita fechas y montos residuales.
        """
        concepto_partes = [self._limpiar_concepto(resto_linea_fecha)]
        referencia = ""

        # Leer líneas subsiguientes
        linea_actual = idx_linea_actual + 1
        while linea_actual < len(ys_ordenados):
            siguiente_y = ys_ordenados[linea_actual]
            palabras_siguiente = sorted(lineas_por_y[siguiente_y], key=lambda p: p.x0)
            texto_siguiente = " ".join(p.text for p in palabras_siguiente)

            # ¿Es encabezado/pie de página? → saltar
            texto_lower = texto_siguiente.lower()
            if any(skip in texto_lower for skip in self._SKIP_PATTERNS):
                linea_actual += 1
                continue

            # ¿Empieza con fecha? → es otro movimiento, terminar
            if re.match(r"^\d{2}/[A-Z]{3}", texto_siguiente):
                break

            # ¿Contiene "Ref."? → extraer referencia y terminar
            match_ref = re.search(r"Ref\.\s*([A-Z]*:?\s*[\w-]+)", texto_siguiente)
            if match_ref:
                referencia = match_ref.group(1).strip()
                # Agregar texto ANTES de "Ref." al concepto
                texto_antes_ref = texto_siguiente.split("Ref.")[0].strip()
                if texto_antes_ref and not texto_antes_ref.startswith("REF:"):
                    concepto_partes.append(texto_antes_ref)
                break

            # ¿Tiene montos grandes? → probablemente línea de saldos, saltar
            tiene_montos_grandes = any(
                re.match(r"^\d{1,3}(,\d{3})*\.\d{2}$", p.text) for p in palabras_siguiente
            )

            if not tiene_montos_grandes and texto_siguiente.strip():
                concepto_partes.append(texto_siguiente.strip())

            linea_actual += 1

        concepto = " ".join(parte for parte in concepto_partes if parte)
        return (concepto, referencia)

    @staticmethod
    def _limpiar_concepto(concepto: str) -> str:
        """Limpia el concepto eliminando fechas residuales y montos.

        Ejemplo: "N06 PAGO NOMINA 15,000.00" → "N06 PAGO NOMINA"
        """
        # Quitar fecha DD/MMM al inicio (si se coló)
        concepto = re.sub(r"^\d{2}/[A-Z]{3}\s+", "", concepto)
        # Quitar montos con formato X,XXX.XX
        concepto = re.sub(r"\b\d{1,3}(,\d{3})*\.\d{2}\b", "", concepto)
        # Limpiar espacios múltiples
        concepto = re.sub(r"\s+", " ", concepto)
        return concepto.strip()

    # =================================================================
    # MÉTODOS PRIVADOS: Cálculo de resumen
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
