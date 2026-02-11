"""
Tests para la lógica de merge de PDFs híbridos en StatementProcessor.

BUG: Algunos PDFs de Vantage Bank tienen páginas mixtas: unas con texto
embebido (pdfplumber las lee) y otras que son imágenes puras (0 chars).
Ejemplo: mayo 2025 tiene página 1 con texto (depósitos) pero páginas
2-3 como imágenes (retiros = OTROS DEBITOS, 56 registros).

El viejo código de _extract_with_fallback hacía:
    if pages and not all(p.is_empty for p in pages):
        return pages  # ← Página 1 tiene texto → devuelve TODO sin OCR

Como la página 1 tenía texto, la condición era True y devolvía las 4
páginas sin activar OCR. Las páginas 2-3 llegaban vacías al parser
→ 0 retiros extraídos.

FIX: Se implementó detección de PDFs híbridos con merge inteligente:
1. pdfplumber extrae → detecta que 3/4 páginas están vacías
2. Guarda resultado parcial, activa OCR como fallback
3. OCR extrae las 4 páginas
4. _merge_hybrid_pages() combina: pdfplumber para pág 1 (texto exacto)
   y OCR para págs 2-3-4 (que solo existían como imagen)
"""


from src.domain.models.page_text import PageText
from src.domain.services.statement_processor import StatementProcessor


class TestMergeHybridPages:
    """Tests unitarios para StatementProcessor._merge_hybrid_pages().

    Este método estático combina páginas de dos extractores para PDFs
    donde algunas páginas tienen texto nativo y otras son imágenes.
    """

    def test_paginas_vacias_se_rellenan_con_ocr(self):
        """Páginas vacías en primary se rellenan con texto de secondary.

        Este es el caso principal: pdfplumber extrae la pág 1 con texto,
        pero las págs 2-3 están vacías (son imágenes). OCR extrae todo.
        El merge debe usar pdfplumber para pág 1 y OCR para págs 2-3.
        """
        primary = [
            PageText(page_num=1, text="Texto página 1 (pdfplumber)"),
            PageText(page_num=2, text=""),  # imagen
            PageText(page_num=3, text=""),  # imagen
        ]
        secondary = [
            PageText(page_num=1, text="Texto OCR página 1 (menos preciso)"),
            PageText(page_num=2, text="Texto OCR página 2 (OTROS DEBITOS)"),
            PageText(page_num=3, text="Texto OCR página 3 (más débitos)"),
        ]

        merged = StatementProcessor._merge_hybrid_pages(primary, secondary)

        assert len(merged) == 3
        # Pág 1: usa pdfplumber (más preciso)
        assert merged[0].text == "Texto página 1 (pdfplumber)"
        # Págs 2-3: usa OCR (único disponible)
        assert merged[1].text == "Texto OCR página 2 (OTROS DEBITOS)"
        assert merged[2].text == "Texto OCR página 3 (más débitos)"

    def test_pdfplumber_tiene_prioridad_sobre_ocr(self):
        """Cuando ambos extractores tienen texto para una página,
        se usa pdfplumber porque es más preciso (sin errores de OCR).

        Ejemplo: "1,000,000.00" con pdfplumber vs "1,000 000.00" con OCR.
        """
        primary = [
            PageText(page_num=1, text="1,000,000.00 exacto"),
            PageText(page_num=2, text="Texto nativo página 2"),
        ]
        secondary = [
            PageText(page_num=1, text="1,000 000.00 OCR impreciso"),
            PageText(page_num=2, text="Texto OCR página 2"),
        ]

        merged = StatementProcessor._merge_hybrid_pages(primary, secondary)

        assert merged[0].text == "1,000,000.00 exacto"
        assert merged[1].text == "Texto nativo página 2"

    def test_ambas_vacias_pasan_pagina_vacia(self):
        """Si tanto primary como secondary están vacías para una página,
        se pasa la vacía (ej: página 4 = formulario sin contenido).
        """
        primary = [
            PageText(page_num=1, text="Texto pág 1"),
            PageText(page_num=2, text=""),
        ]
        secondary = [
            PageText(page_num=1, text="OCR pág 1"),
            PageText(page_num=2, text=""),  # formulario sin texto
        ]

        merged = StatementProcessor._merge_hybrid_pages(primary, secondary)

        assert merged[0].text == "Texto pág 1"
        assert merged[1].is_empty

    def test_secondary_mas_corto_que_primary(self):
        """Si OCR devuelve menos páginas que pdfplumber, las páginas
        faltantes se mantienen como vacías del primary.
        """
        primary = [
            PageText(page_num=1, text="Pág 1"),
            PageText(page_num=2, text=""),
            PageText(page_num=3, text=""),
        ]
        secondary = [
            PageText(page_num=1, text="OCR Pág 1"),
            # OCR solo pudo procesar 1 página
        ]

        merged = StatementProcessor._merge_hybrid_pages(primary, secondary)

        assert len(merged) == 3
        assert merged[0].text == "Pág 1"
        assert merged[1].is_empty  # no hay OCR para esta
        assert merged[2].is_empty  # no hay OCR para esta

    def test_todas_primary_con_texto_ignora_secondary(self):
        """Si primary tiene texto en TODAS las páginas, secondary
        se ignora completamente (no se mezcla nada).
        """
        primary = [
            PageText(page_num=1, text="Texto completo pág 1"),
            PageText(page_num=2, text="Texto completo pág 2"),
        ]
        secondary = [
            PageText(page_num=1, text="OCR innecesario pág 1"),
            PageText(page_num=2, text="OCR innecesario pág 2"),
        ]

        merged = StatementProcessor._merge_hybrid_pages(primary, secondary)

        assert merged[0].text == "Texto completo pág 1"
        assert merged[1].text == "Texto completo pág 2"

    def test_caso_real_vantage_mayo(self):
        """Simula el caso real de Vantage Bank mayo 2025:
        - Página 1: texto (OTROS CREDITOS = 17 depósitos)
        - Página 2: imagen (OTROS DEBITOS = parte 1 de retiros)
        - Página 3: imagen (OTROS DEBITOS = parte 2 de retiros)
        - Página 4: imagen (formulario vacío, sin movimientos)
        """
        primary = [
            PageText(
                page_num=1,
                text="OTROS CREDITOS\nWIRE TRANSFER 05-01 462,822.89\n"
                "Total 21,301,312.27",
            ),
            PageText(page_num=2, text=""),  # imagen
            PageText(page_num=3, text=""),  # imagen
            PageText(page_num=4, text=""),  # formulario
        ]
        secondary = [
            PageText(page_num=1, text="OTROS CREDITOS OCR (menos preciso)"),
            PageText(
                page_num=2,
                text="OTROS DEBITOS\nTransfer to DDA 05-06 5,465.19\n"
                "WIRE TRANSFER 05-06 100,000.00",
            ),
            PageText(
                page_num=3,
                text="OTROS DEBITOS\n"
                "WIRE MXN TO PRADERAS 05-28 2,000,000.00\n"
                "Total 20,649,810.52",
            ),
            PageText(page_num=4, text=""),  # formulario sin texto
        ]

        merged = StatementProcessor._merge_hybrid_pages(primary, secondary)

        assert len(merged) == 4
        # Pág 1: pdfplumber (texto exacto de depósitos)
        assert "OTROS CREDITOS" in merged[0].text
        assert "21,301,312.27" in merged[0].text
        # Pág 2: OCR (retiros parte 1)
        assert "OTROS DEBITOS" in merged[1].text
        assert "5,465.19" in merged[1].text
        # Pág 3: OCR (retiros parte 2)
        assert "2,000,000.00" in merged[2].text
        # Pág 4: vacía (formulario)
        assert merged[3].is_empty

    def test_paginas_numeracion_se_preserva(self):
        """Los números de página originales se preservan en el merge."""
        primary = [
            PageText(page_num=1, text="Pág 1"),
            PageText(page_num=2, text=""),
        ]
        secondary = [
            PageText(page_num=1, text="OCR 1"),
            PageText(page_num=2, text="OCR 2"),
        ]

        merged = StatementProcessor._merge_hybrid_pages(primary, secondary)

        # La pág 2 viene de secondary, pero mantiene page_num=2
        assert merged[1].page_num == 2