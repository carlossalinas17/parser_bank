"""
Adaptador de entrada: Extractor de texto por OCR (pytesseract + pdf2image).

Este extractor es el FALLBACK para PDFs que no tienen texto embebido
(PDFs escaneados / imagen-only). Lo usa el StatementProcessor cuando
PdfplumberExtractor devuelve páginas vacías.

Workflow:
1. pdf2image convierte cada página del PDF a una imagen PIL (300 DPI).
2. pytesseract ejecuta OCR sobre cada imagen.
3. El texto resultante se envuelve en PageText del dominio.

¿Por qué 300 DPI?
Es el balance entre calidad de OCR y velocidad. 150 DPI pierde detalle
en números pequeños (montos). 600 DPI es más lento sin mejora notable.

¿Por qué spa+eng?
Vantage Bank (el caso principal) mezcla español e inglés en sus PDFs.
Tesseract soporta múltiples idiomas simultáneamente.

Dependencias externas:
- pytesseract (wrapper Python de Tesseract OCR)
- pdf2image (wrapper de poppler-utils para convertir PDF a imagen)
- Tesseract OCR (binario del sistema, instalado con apt)
- poppler-utils (binario del sistema, para pdf2image)
"""

import platform
from pathlib import Path

from src.domain.exceptions import ExtractionError, FormatoInvalidoError
from src.domain.models.page_text import PageText
from src.domain.ports.text_extractor import TextExtractor
from src.domain.shared.text_cleaner import clean_pdf_text

# Imports lazy: solo se cargan cuando se usan.
try:
    import pytesseract

    # En Windows, Tesseract no se agrega al PATH automáticamente.
    # Hay que indicarle a pytesseract dónde está el ejecutable.
    # En Linux/Mac esto no es necesario porque apt/brew lo pone en /usr/bin/.
    if platform.system() == "Windows" and pytesseract is not None:
        _TESSERACT_WINDOWS_PATHS = [
            Path.home() / "AppData/Local/Programs/Tesseract-OCR/tesseract.exe",
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for _path in _TESSERACT_WINDOWS_PATHS:
            if _path.exists():
                pytesseract.pytesseract.tesseract_cmd = str(_path)
                break

except ImportError:
    pytesseract = None  # type: ignore[assignment]

try:
    from pdf2image import convert_from_path
except ImportError:
    convert_from_path = None  # type: ignore[assignment]


class OcrExtractor(TextExtractor):
    """Extrae texto de PDFs escaneados usando OCR.

    Este extractor NO genera WordInfo (coordenadas X/Y) porque
    pytesseract no produce posiciones confiables a nivel de palabra.
    Por tanto, solo funciona con parsers que operan sobre texto plano
    (Santander, Scotiabank, Vantage Bank) y NO con parsers que
    necesitan coordenadas (BBVA, Banorte).
    """

    def __init__(
        self,
        dpi: int = 300,
        lang: str = "spa+eng",
    ) -> None:
        """
        Args:
            dpi: Resolución para la conversión PDF→imagen.
                 300 es el balance entre calidad OCR y velocidad.
            lang: Idiomas para Tesseract (formato "lang1+lang2").
                  "spa+eng" cubre PDFs mexicanos con texto en inglés.
                  Si "spa" no está instalado, se hace fallback a "eng".
        """
        self._dpi = dpi
        self._lang = lang
        self._lang_fallback = "eng"  # Fallback si spa no disponible

    @property
    def name(self) -> str:
        return "ocr-tesseract"

    def can_handle(self, file_path: Path) -> bool:
        """Puede manejar archivos PDF.

        Este extractor tiene la misma extensión que PdfplumberExtractor,
        pero se registra DESPUÉS en la lista de extractores. El
        StatementProcessor intenta PdfplumberExtractor primero y solo
        usa OcrExtractor si el primero devuelve páginas vacías.
        """
        return file_path.suffix.lower() == ".pdf"

    def extract(self, file_path: Path) -> list[PageText]:
        """Extrae texto de cada página del PDF mediante OCR.

        Pasos:
        1. Convierte cada página a imagen PIL (300 DPI por defecto).
        2. Ejecuta Tesseract OCR sobre cada imagen.
        3. Limpia el texto resultante con clean_pdf_text.

        Returns:
            Lista de PageText con el texto de OCR.

        Raises:
            ExtractionError: Si pytesseract/pdf2image no están
                            instalados o si falla la conversión/OCR.
            FormatoInvalidoError: Si el archivo no existe o no es PDF.
        """
        # --- Validaciones previas ---
        if pytesseract is None:
            raise ExtractionError(
                str(file_path),
                "pytesseract no está instalado. " "Instalar con: pip install pytesseract",
            )

        if convert_from_path is None:
            raise ExtractionError(
                str(file_path),
                "pdf2image no está instalado. " "Instalar con: pip install pdf2image",
            )

        if not file_path.exists():
            raise FormatoInvalidoError(str(file_path), "PDF", "El archivo no existe")

        if file_path.suffix.lower() != ".pdf":
            raise FormatoInvalidoError(
                str(file_path),
                "PDF",
                f"Extensión inesperada: {file_path.suffix}",
            )

        # --- Conversión PDF → imágenes ---
        try:
            images = convert_from_path(str(file_path), dpi=self._dpi)
        except Exception as e:
            raise ExtractionError(
                str(file_path),
                f"Error al convertir PDF a imágenes: {e}",
            )

        if not images:
            raise ExtractionError(
                str(file_path),
                "pdf2image no produjo ninguna imagen.",
            )

        # --- OCR sobre cada imagen ---
        pages: list[PageText] = []

        # Determinar idioma disponible para Tesseract.
        # Algunos entornos solo tienen 'eng' instalado, no 'spa'.
        # Si 'spa+eng' falla en la primera imagen, hacemos fallback a 'eng'.
        lang_efectivo = self._resolve_lang()

        for page_num, image in enumerate(images, start=1):
            try:
                raw_text = pytesseract.image_to_string(image, lang=lang_efectivo)
            except Exception:
                # Si falla el OCR de una página, continuar con las demás
                raw_text = ""

            cleaned_text = clean_pdf_text(raw_text)

            pages.append(
                PageText(
                    page_num=page_num,
                    text=cleaned_text,
                    # OCR no produce coordenadas confiables
                    words=[],
                )
            )

        return pages

    def _resolve_lang(self) -> str:
        """Determina qué idioma(s) de Tesseract usar.

        Intenta usar el idioma configurado (por defecto 'spa+eng').
        Si alguno de los idiomas no está instalado, hace fallback
        a 'eng' que siempre está disponible.

        ¿Por qué no simplemente usar 'eng'?
        Porque 'spa+eng' mejora la precisión del OCR en PDFs que
        mezclan español e inglés (como Vantage Bank). El fallback
        a 'eng' es un compromiso aceptable: el OCR será menos preciso
        en acentos (á, é, ñ) pero los datos financieros (fechas,
        montos, nombres de empresa) se leen igual de bien.

        Returns:
            String de idioma para Tesseract (ej: 'spa+eng' o 'eng').
        """
        if pytesseract is None:
            return self._lang

        try:
            # Verificar qué idiomas tiene Tesseract instalados
            available = pytesseract.get_languages()
            requested = self._lang.split("+")
            missing = [lg for lg in requested if lg not in available]

            if not missing:
                return self._lang

            # Hay idiomas faltantes → intentar fallback
            if self._lang_fallback in available:
                return self._lang_fallback

            # Ni el fallback está → usar lo que haya (menos 'osd')
            usable = [lg for lg in available if lg != "osd"]
            if usable:
                return "+".join(usable)

            return self._lang  # Última instancia, dejar que falle naturalmente

        except Exception:
            # Si get_languages() falla, intentar con el idioma configurado
            return self._lang
