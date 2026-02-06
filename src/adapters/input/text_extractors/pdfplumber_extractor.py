"""
Adaptador de entrada: Extractor de texto usando pdfplumber.

pdfplumber es la librería principal para leer PDFs nativos (con texto
embebido). La usan 15 de los 17 extractores originales.

Este adaptador:
1. Abre el PDF con pdfplumber.
2. Extrae el texto plano de cada página (extract_text).
3. Opcionalmente extrae palabras con coordenadas (extract_words),
   necesario para parsers como BBVA que clasifican por posición X.
4. Envuelve todo en objetos PageText del dominio.

¿Por qué separar el extractor del parser?
Porque así el parser de BBVA no sabe que existe pdfplumber. Recibe
PageText y opera sobre texto/palabras. Si mañana cambiamos de librería
(por ejemplo a PyMuPDF), solo cambiamos este archivo.
"""

from pathlib import Path

from src.domain.exceptions import ExtractionError, FormatoInvalidoError
from src.domain.models.page_text import PageText
from src.domain.models.word_info import WordInfo
from src.domain.ports.text_extractor import TextExtractor
from src.domain.shared.text_cleaner import clean_pdf_text

# Import lazy: pdfplumber es pesado, solo se importa cuando se usa.
# Esto permite que el proyecto se importe sin tener pdfplumber instalado
# (por ejemplo, en entornos donde solo se usa OCR).
try:
    import pdfplumber
except ImportError:
    pdfplumber = None  # type: ignore[assignment]


class PdfplumberExtractor(TextExtractor):
    """Extrae texto de PDFs nativos usando pdfplumber.

    Soporta dos modos:
    - Solo texto (por defecto): rápido, suficiente para la mayoría de bancos.
    - Texto + palabras con coordenadas: necesario para BBVA, Banorte, etc.
      que clasifican columnas por posición X.
    """

    def __init__(self, include_words: bool = True) -> None:
        """
        Args:
            include_words: Si True, extrae también las palabras con sus
                          coordenadas X/Y. Más lento pero necesario para
                          parsers que dependen de posiciones de columnas.
                          Por defecto True porque la mayoría de los bancos
                          mexicanos lo necesitan.
        """
        self._include_words = include_words

    @property
    def name(self) -> str:
        return "pdfplumber"

    def can_handle(self, file_path: Path) -> bool:
        """Puede manejar archivos con extensión .pdf.

        No verifica si el PDF tiene texto embebido (eso se detecta después
        al intentar extraer — si no hay texto, es candidato para OCR).
        """
        return file_path.suffix.lower() == ".pdf"

    def extract(self, file_path: Path) -> list[PageText]:
        """Extrae texto (y opcionalmente palabras) de cada página del PDF.

        Returns:
            Lista de PageText, una por página. Páginas sin texto se incluyen
            con text="" para mantener la correspondencia page_num ↔ índice.

        Raises:
            ExtractionError: Si pdfplumber no puede abrir el PDF
                            (corrupto, protegido con contraseña, etc.)
            FormatoInvalidoError: Si el archivo no existe o no es PDF.
        """
        # --- Validaciones previas ---
        if pdfplumber is None:
            raise ExtractionError(
                str(file_path),
                "pdfplumber no está instalado. " "Instalar con: pip install pdfplumber",
            )

        if not file_path.exists():
            raise FormatoInvalidoError(str(file_path), "PDF", "El archivo no existe")

        if file_path.suffix.lower() != ".pdf":
            raise FormatoInvalidoError(
                str(file_path),
                "PDF",
                f"Extensión inesperada: {file_path.suffix}",
            )

        # --- Extracción ---
        pages: list[PageText] = []

        try:
            with pdfplumber.open(file_path) as pdf:
                if len(pdf.pages) == 0:
                    raise ExtractionError(str(file_path), "El PDF no tiene páginas")

                for page_num, page in enumerate(pdf.pages, start=1):
                    # Extraer texto plano
                    raw_text = page.extract_text() or ""
                    cleaned_text = clean_pdf_text(raw_text)

                    # Extraer palabras con coordenadas (si se solicitó)
                    words: list[WordInfo] = []
                    if self._include_words:
                        raw_words = page.extract_words() or []
                        words = [
                            WordInfo(
                                text=w["text"],
                                x0=float(w["x0"]),
                                x1=float(w["x1"]),
                                top=float(w["top"]),
                                bottom=float(w["bottom"]),
                            )
                            for w in raw_words
                        ]

                    pages.append(
                        PageText(
                            page_num=page_num,
                            text=cleaned_text,
                            words=words,
                        )
                    )

        except pdfplumber.pdfminer.pdfparser.PDFSyntaxError as e:
            raise ExtractionError(str(file_path), f"PDF corrupto o inválido: {e}")
        except Exception as e:
            # Captura genérica para errores inesperados de pdfplumber
            # (PDFs protegidos, encoding roto, etc.)
            if "password" in str(e).lower() or "encrypt" in str(e).lower():
                raise ExtractionError(
                    str(file_path),
                    "El PDF está protegido con contraseña. " "Usar el extractor de PDFs cifrados.",
                )
            raise ExtractionError(str(file_path), str(e))

        return pages
