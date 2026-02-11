"""
Servicio de dominio: Procesador de estados de cuenta.

Orquesta la Fase 2 del workflow:
1. Recibe una ruta a un archivo PDF.
2. Selecciona el TextExtractor adecuado (can_handle).
3. Extrae texto de las páginas.
4. Identifica el banco (BankIdentifier).
5. Obtiene el parser del banco (Registry).
6. Parsea y devuelve ResultadoParseo.

¿Por qué no poner esta lógica en el CLI?
Porque esta orquestación es LÓGICA DE NEGOCIO: "dado un PDF, producir
movimientos" es una regla del dominio. El CLI solo decide QUÉ archivos
procesar y DÓNDE guardar los resultados.
"""

from collections.abc import Sequence
from pathlib import Path

from src.domain.exceptions import BancoNoIdentificadoError, ExtractionError, ParseError
from src.domain.models.page_text import PageText
from src.domain.models.resultado_parseo import ResultadoParseo
from src.domain.ports.bank_identifier import BankIdentifier
from src.domain.ports.process_logger import ProcessLogger
from src.domain.ports.text_extractor import TextExtractor
from src.infrastructure.registry import BankParserRegistry


class StatementProcessor:
    """Procesa un archivo y produce un ResultadoParseo.

    Recibe sus dependencias por constructor (Dependency Injection).
    No sabe qué TextExtractor, BankIdentifier ni BankParsers concretos
    se están usando — solo conoce las interfaces (puertos).
    """

    def __init__(
        self,
        text_extractors: Sequence[TextExtractor],
        bank_identifier: BankIdentifier,
        parser_registry: BankParserRegistry,
        logger: ProcessLogger,
    ) -> None:
        """
        Args:
            text_extractors: Lista de extractores disponibles, en orden de
                            prioridad. Se usa el primero cuyo can_handle
                            devuelva True.
            bank_identifier: Identificador de banco por keywords.
            parser_registry: Registro de parsers disponibles.
            logger: Logger para la bitácora de procesamiento.
        """
        self._extractors = text_extractors
        self._identifier = bank_identifier
        self._registry = parser_registry
        self._logger = logger

    def process_file(self, file_path: Path) -> ResultadoParseo | None:
        """Procesa un archivo y devuelve el resultado.

        Args:
            file_path: Ruta al archivo a procesar.

        Returns:
            ResultadoParseo si el procesamiento fue exitoso.
            None si el archivo fue descartado o hubo un error no fatal.
        """
        # Paso 1: Seleccionar extractor y extraer texto
        #
        # Se prueban los extractores en orden de prioridad. Si el
        # primero (pdfplumber) devuelve páginas vacías, se intenta
        # con el siguiente (OCR). Esto maneja PDFs escaneados como
        # los de Vantage Bank (abril, junio, octubre) que son 100%
        # imagen sin capa de texto.
        self._logger.log_file_received(file_path, file_path.suffix)
        pages = self._extract_with_fallback(file_path)
        if pages is None:
            return None

        # Paso 3: Identificar banco
        # Se usa el texto de las primeras 2 páginas (donde está el encabezado)
        texto_identificacion = "\n".join(p.text for p in pages[:2])
        bank_name = self._identifier.identify(texto_identificacion)

        if bank_name is None:
            self._logger.log_bank_not_identified(file_path)
            return None

        self._logger.log_bank_identified(file_path, bank_name)

        # Paso 4: Obtener parser
        parser = self._registry.get(bank_name)
        if parser is None:
            self._logger.log_error(
                file_path,
                BancoNoIdentificadoError(
                    str(file_path),
                    f"Banco '{bank_name}' identificado pero no tiene parser "
                    f"implementado. Bancos disponibles: "
                    f"{self._registry.available_banks}",
                ),
            )
            return None

        # Paso 5: Parsear
        try:
            resultado = parser.parse(pages, file_name=file_path.name)
        except ParseError as e:
            self._logger.log_error(file_path, e)
            return None

        self._logger.log_extraction_complete(file_path, len(pages), len(resultado.movimientos))
        return resultado

    def process_directory(self, dir_path: Path) -> list[ResultadoParseo]:
        """Procesa todos los archivos PDF de un directorio.

        Args:
            dir_path: Ruta al directorio con PDFs.

        Returns:
            Lista de ResultadoParseo (solo los exitosos).
        """
        if not dir_path.is_dir():
            raise ValueError(f"No es un directorio: {dir_path}")

        # Buscar todos los PDFs (recursivo)
        archivos = sorted(dir_path.glob("**/*.pdf"))

        if not archivos:
            print(f"No se encontraron archivos PDF en {dir_path}")
            return []

        resultados: list[ResultadoParseo] = []
        for archivo in archivos:
            resultado = self.process_file(archivo)
            if resultado is not None:
                resultados.append(resultado)

        return resultados

    def _find_extractor(self, file_path: Path) -> TextExtractor | None:
        """Encuentra el primer extractor que pueda manejar el archivo.

        Itera por la lista de extractores en orden de prioridad y
        devuelve el primero cuyo can_handle devuelva True.
        """
        for extractor in self._extractors:
            if extractor.can_handle(file_path):
                return extractor
        return None

    def _extract_with_fallback(
        self, file_path: Path
    ) -> list[PageText] | None:
        """Intenta extraer texto probando extractores en orden.

        Si el primer extractor (pdfplumber) devuelve páginas vacías,
        intenta con el siguiente (OCR). Esto es transparente para el
        resto del pipeline — el parser recibe PageText sin importar
        de qué extractor vino.

        CASO ESPECIAL — PDFs HÍBRIDOS:
        Algunos PDFs de Vantage Bank (y posiblemente otros bancos) tienen
        páginas mixtas: unas con texto embebido y otras que son imagen pura.
        Ejemplo: mayo 2025 tiene página 1 con texto (depósitos) pero
        páginas 2-3 como imagen (retiros). En este caso:
        1. pdfplumber extrae texto de la página 1 → OK
        2. pdfplumber devuelve páginas 2-3 vacías → problema
        3. Como página 1 tiene texto, el fallback a OCR NO se activa
        4. Los retiros de las páginas 2-3 se pierden completamente

        FIX: Si pdfplumber devuelve ALGUNAS páginas vacías, se activa OCR
        SOLO para esas páginas vacías, y se mezcla el resultado. Así:
        - Páginas con texto nativo → se usa pdfplumber (más preciso)
        - Páginas imagen → se usa OCR (único método posible)

        ¿Por qué no simplemente poner OCR primero?
        Porque OCR es lento (~5s por página vs ~0.1s de pdfplumber)
        y menos preciso. Solo se usa cuando pdfplumber no puede
        extraer nada (PDFs escaneados / imagen-only).

        Returns:
            Lista de PageText si algún extractor tuvo éxito.
            None si ningún extractor pudo extraer texto.
        """
        # Filtrar extractores que pueden manejar este archivo
        extractores_compatibles = [
            e for e in self._extractors if e.can_handle(file_path)
        ]

        if not extractores_compatibles:
            self._logger.log_file_skipped(
                file_path,
                f"Ningún extractor puede manejar '{file_path.suffix}'",
            )
            return None

        first_result: list[PageText] | None = None

        for extractor in extractores_compatibles:
            self._logger.log_extraction_start(file_path, extractor.name)

            try:
                pages = extractor.extract(file_path)
            except ExtractionError as e:
                self._logger.log_error(file_path, e)
                continue  # Probar siguiente extractor

            # Si ya tenemos resultado parcial (PDF híbrido) y el nuevo
            # extractor produjo algo, mezclar los resultados:
            # - Páginas con texto nativo (pdfplumber) → se conservan
            # - Páginas vacías → se rellenan con OCR
            if first_result is not None and pages:
                merged = self._merge_hybrid_pages(first_result, pages)
                if merged and not all(p.is_empty for p in merged):
                    return merged
                # Si aún quedan vacías después del merge, continuar
                first_result = merged
                continue

            # Caso 1: TODAS las páginas tienen texto → éxito total
            if pages and not any(p.is_empty for p in pages):
                return pages

            # Caso 2: ALGUNAS páginas tienen texto (PDF híbrido)
            #
            # Guardar este resultado parcial. El siguiente extractor
            # (OCR) producirá texto para las páginas faltantes, y se
            # mezclarán en la siguiente iteración del loop.
            if pages and not all(p.is_empty for p in pages):
                empty_count = sum(1 for p in pages if p.is_empty)
                total_count = len(pages)
                first_result = pages

                self._logger.log_file_skipped(
                    file_path,
                    f"PDF híbrido: {empty_count}/{total_count} páginas "
                    f"sin texto con {extractor.name}, "
                    f"intentando OCR en páginas vacías...",
                )
                continue

            # Caso 3: TODAS las páginas vacías → intentar siguiente extractor
            self._logger.log_file_skipped(
                file_path,
                f"Sin texto con {extractor.name}, intentando siguiente...",
            )

        # Si el OCR no produjo nada pero teníamos resultado parcial,
        # devolver lo que el primer extractor pudo sacar
        if first_result is not None and not all(p.is_empty for p in first_result):
            return first_result

        # Ningún extractor produjo texto
        self._logger.log_file_skipped(
            file_path, "PDF sin texto extraíble (ni nativo ni OCR)"
        )
        return None

    @staticmethod
    def _merge_hybrid_pages(
        primary: list[PageText],
        secondary: list[PageText],
    ) -> list[PageText]:
        """Mezcla páginas de dos extractores para PDFs híbridos.

        Para cada página, usa el texto del extractor primario (pdfplumber)
        si está disponible. Si la página primaria está vacía, usa el
        texto del extractor secundario (OCR).

        ¿Por qué preferir pdfplumber sobre OCR?
        Porque el texto nativo de pdfplumber es exacto (sin errores de OCR).
        Los montos "1,000,000.00" se leen perfectos con pdfplumber, pero
        OCR puede producir "1,000 000.00" o "1,000,000. 00". Solo se usa
        OCR cuando no hay alternativa.

        Args:
            primary: Páginas del primer extractor (pdfplumber).
                     Algunas pueden estar vacías.
            secondary: Páginas del segundo extractor (OCR).
                       Idealmente todas tienen texto.

        Returns:
            Lista de PageText mezcladas. Misma longitud que primary.
        """
        merged: list[PageText] = []

        for i, page in enumerate(primary):
            if not page.is_empty:
                # Página primaria tiene texto → usarla
                merged.append(page)
            elif i < len(secondary) and not secondary[i].is_empty:
                # Página primaria vacía, pero OCR tiene texto → usar OCR
                merged.append(secondary[i])
            else:
                # Ambas vacías → pasar la vacía (ej: página 4 de formulario)
                merged.append(page)

        return merged