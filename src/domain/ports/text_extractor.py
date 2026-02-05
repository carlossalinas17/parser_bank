"""
Puerto de entrada: Extractor de texto.

Define el contrato para extraer texto de un archivo (PDF, ZIP, CSV, etc.).
Cada tipo de archivo tiene su propio adaptador que implementa este puerto:

    TextExtractor (interfaz)
    ├── PdfplumberExtractor     → PDFs nativos (texto embebido)
    ├── OcrExtractor            → PDFs escaneados (pytesseract)
    ├── ZipTextExtractor        → ZIP con archivos .txt
    ├── PyMuPDFExtractor        → PDFs con PyMuPDF/fitz (BX+)
    ├── EncryptedExtractor      → PDFs cifrados (reemplazo de chars)
    └── CsvExtractor            → Archivos CSV/Excel como entrada

¿Por qué es una Abstract Base Class (ABC)?
Porque queremos que Python lance un error si alguien crea un adaptador
que no implementa todos los métodos. Sin ABC, el error aparecería en
tiempo de ejecución cuando se llame al método faltante, lo cual es
más difícil de debuggear.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from src.domain.models.page_text import PageText


class TextExtractor(ABC):
    """Interfaz para extraer texto de un archivo."""

    @abstractmethod
    def can_handle(self, file_path: Path) -> bool:
        """Determina si este extractor puede manejar el archivo dado.

        El StatementProcessor itera por todos los extractores registrados
        y usa el primero cuyo can_handle devuelva True. Esto permite
        seleccionar automáticamente el extractor correcto sin hardcodear
        lógica de "si es PDF usa pdfplumber, si es ZIP usa otro".

        Args:
            file_path: Ruta al archivo a evaluar.

        Returns:
            True si este extractor puede procesar el archivo.
            False si no puede (y se debe probar con otro extractor).
        """
        ...

    @abstractmethod
    def extract(self, file_path: Path) -> list[PageText]:
        """Extrae el texto del archivo, separado por páginas.

        Args:
            file_path: Ruta al archivo del cual extraer texto.

        Returns:
            Lista de PageText, una por cada página del documento.
            Para archivos sin concepto de "páginas" (como CSV),
            se devuelve una sola PageText con todo el contenido.

        Raises:
            ExtractionError: Si falla la extracción (archivo corrupto,
                            librería no disponible, etc.)
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Nombre legible del extractor. Para logging y debugging.

        Ejemplo: 'pdfplumber', 'ocr-tesseract', 'zip-text'
        """
        ...
