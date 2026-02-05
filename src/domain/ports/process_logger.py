"""
Puerto de salida: Bitácora de procesamiento (Process Logger).

Define el contrato para registrar eventos durante el procesamiento
de estados de cuenta. Reemplaza los print() del código original.

¿Por qué no usar simplemente el módulo `logging` de Python?
Porque `logging` es una herramienta de infraestructura (HOW), mientras que
este puerto define los EVENTOS de negocio (WHAT):
- "Se recibió un archivo" (no "INFO: archivo recibido")
- "No se pudo identificar el banco" (no "WARNING: banco desconocido")

La implementación puede usar `logging` internamente, pero el dominio
solo conoce los eventos de negocio. Esto permite:
- En producción: escribir a archivo con logging.
- En desarrollo: imprimir a consola con colores.
- En tests: acumular en memoria y hacer asserts.
- En N8N: enviar a un webhook.
"""

from abc import ABC, abstractmethod
from pathlib import Path


class ProcessLogger(ABC):
    """Interfaz para la bitácora de procesamiento."""

    # --- Fase 1: Limpieza de archivos ---

    @abstractmethod
    def log_file_received(self, file_path: Path, file_type: str) -> None:
        """Registra que se recibió un archivo para procesar.

        Args:
            file_path: Ruta del archivo.
            file_type: Tipo detectado: 'pdf', 'zip', 'csv', 'otro'.
        """
        ...

    @abstractmethod
    def log_file_skipped(self, file_path: Path, reason: str) -> None:
        """Registra que un archivo fue descartado (no es PDF/ZIP/CSV).

        Args:
            file_path: Ruta del archivo descartado.
            reason: Razón del descarte. Ejemplo: "Extensión .docx no soportada"
        """
        ...

    # --- Fase 2: Procesamiento ---

    @abstractmethod
    def log_bank_identified(self, file_path: Path, bank_name: str) -> None:
        """Registra que se identificó el banco de un estado de cuenta."""
        ...

    @abstractmethod
    def log_bank_not_identified(self, file_path: Path) -> None:
        """Registra que no se pudo identificar el banco."""
        ...

    @abstractmethod
    def log_extraction_start(self, file_path: Path, extractor_name: str) -> None:
        """Registra el inicio de extracción de texto."""
        ...

    @abstractmethod
    def log_extraction_complete(
        self, file_path: Path, num_pages: int, num_movimientos: int
    ) -> None:
        """Registra el fin exitoso de extracción y parseo.

        Args:
            file_path: Ruta del archivo procesado.
            num_pages: Cantidad de páginas procesadas.
            num_movimientos: Cantidad de movimientos extraídos.
        """
        ...

    @abstractmethod
    def log_error(self, file_path: Path, error: Exception) -> None:
        """Registra un error durante el procesamiento.

        Se espera que la implementación capture el traceback completo
        para facilitar debugging.
        """
        ...

    # --- Fase 3: Consolidación ---

    @abstractmethod
    def log_consolidation_start(self, num_files: int) -> None:
        """Registra el inicio de la consolidación."""
        ...

    @abstractmethod
    def log_consolidation_complete(self, output_path: Path) -> None:
        """Registra el fin exitoso de la consolidación."""
        ...

    @abstractmethod
    def log_validation_mismatch(
        self,
        file_path: Path,
        field: str,
        expected: str,
        actual: str,
    ) -> None:
        """Registra una discrepancia en la validación cruzada.

        Se usa cuando los totales del PDF no coinciden con los calculados.

        Args:
            file_path: Archivo donde se encontró la discrepancia.
            field: Campo con discrepancia (ej: 'total_depositos').
            expected: Valor esperado (del PDF).
            actual: Valor calculado (de los movimientos parseados).
        """
        ...

    # --- Resumen ---

    @abstractmethod
    def get_summary(self) -> dict:
        """Devuelve un resumen de todo el procesamiento.

        Returns:
            Diccionario con métricas:
            {
                'archivos_recibidos': int,
                'archivos_procesados': int,
                'archivos_descartados': int,
                'archivos_con_error': int,
                'total_movimientos': int,
                'errores': List[dict],  # [{archivo, error}]
            }
        """
        ...
