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

from pathlib import Path

from src.domain.exceptions import BancoNoIdentificadoError, ExtractionError, ParseError
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
        text_extractors: list[TextExtractor],
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
        # Paso 1: Seleccionar extractor
        extractor = self._find_extractor(file_path)
        if extractor is None:
            self._logger.log_file_skipped(
                file_path, f"Ningún extractor puede manejar '{file_path.suffix}'"
            )
            return None

        self._logger.log_file_received(file_path, file_path.suffix)
        self._logger.log_extraction_start(file_path, extractor.name)

        # Paso 2: Extraer texto
        try:
            pages = extractor.extract(file_path)
        except ExtractionError as e:
            self._logger.log_error(file_path, e)
            return None

        if not pages or all(p.is_empty for p in pages):
            self._logger.log_file_skipped(file_path, "PDF sin texto extraíble")
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
