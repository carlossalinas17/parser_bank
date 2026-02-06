"""
Punto de entrada CLI: bank-parser.

Uso:
    # Procesar un solo PDF
    bank-parser /ruta/estado_bbva.pdf -o /ruta/salida

    # Procesar todos los PDFs de una carpeta
    bank-parser /ruta/carpeta_pdfs -o /ruta/salida

    # Sin -o, genera el Excel en el mismo directorio del PDF
    bank-parser /ruta/estado_bbva.pdf

Este módulo es el ÚNICO lugar donde se ensamblan los componentes:
- Crea las instancias concretas (PdfplumberExtractor, ExcelWriter, etc.)
- Las inyecta en el StatementProcessor.
- Ejecuta el procesamiento.

No contiene lógica de negocio — solo "fontanería" (wiring).
"""

import argparse
import sys
from pathlib import Path

from src.adapters.input.bank_identifiers.keyword_identifier import (
    KeywordBankIdentifier,
)
from src.adapters.input.text_extractors.pdfplumber_extractor import (
    PdfplumberExtractor,
)
from src.adapters.output.loggers.console_logger import ConsoleLogger
from src.adapters.output.writers.excel_writer import ExcelWriter
from src.domain.services.statement_processor import StatementProcessor
from src.infrastructure.registry import create_default_registry


def main() -> None:
    """Punto de entrada principal del CLI."""
    args = _parse_args()

    input_path = Path(args.input_path)
    output_dir = Path(args.output_dir) if args.output_dir else None

    # --- Ensamblar componentes ---
    # Aquí es donde se conectan todas las piezas. Si quisiéramos
    # cambiar el extractor (ej: usar OCR en vez de pdfplumber),
    # solo cambiaríamos esta sección. El dominio no se toca.

    logger = ConsoleLogger()

    text_extractors = [
        PdfplumberExtractor(include_words=True),
        # Aquí se agregarían otros extractores en orden de prioridad:
        # OcrExtractor(),
        # ZipTextExtractor(),
    ]

    bank_identifier = KeywordBankIdentifier()
    parser_registry = create_default_registry()
    excel_writer = ExcelWriter()

    processor = StatementProcessor(
        text_extractors=text_extractors,
        bank_identifier=bank_identifier,
        parser_registry=parser_registry,
        logger=logger,
    )

    # --- Determinar directorio de salida ---
    if output_dir is None:
        output_dir = input_path.parent if input_path.is_file() else input_path
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Procesar ---
    print("=" * 60)
    print("BANK STATEMENT PARSER")
    print("=" * 60)
    print(f"  Entrada:  {input_path}")
    print(f"  Salida:   {output_dir}")
    print(f"  Bancos disponibles: {', '.join(parser_registry.available_banks)}")
    print()

    if input_path.is_file():
        # Procesar un solo archivo
        resultado = processor.process_file(input_path)
        if resultado is not None:
            output_file = output_dir / f"movimientos_{input_path.stem}.xlsx"
            excel_writer.write_single(resultado, output_file)
            print(f"\n📁 Excel generado: {output_file}")
        else:
            print("\n❌ No se pudo procesar el archivo.")
            sys.exit(1)

    elif input_path.is_dir():
        # Procesar todos los PDFs de un directorio
        resultados = processor.process_directory(input_path)

        if resultados:
            # Generar Excel individual por cada resultado
            for resultado in resultados:
                nombre_base = Path(resultado.archivo_origen).stem
                output_file = output_dir / f"movimientos_{nombre_base}.xlsx"
                excel_writer.write_single(resultado, output_file)

            # Generar consolidado si hay más de un resultado
            if len(resultados) > 1:
                consolidado_path = output_dir / "consolidado.xlsx"
                excel_writer.write_consolidated(resultados, consolidado_path)
                print(f"\n📁 Consolidado generado: {consolidado_path}")
        else:
            print("\n❌ No se procesó ningún archivo.")
            sys.exit(1)

    else:
        print(f"❌ La ruta no existe: {input_path}")
        sys.exit(1)

    # --- Resumen final ---
    logger.print_summary()


def _parse_args() -> argparse.Namespace:
    """Parsea los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Extractor y consolidador de estados de cuenta bancarios",
        epilog="Ejemplo: bank-parser /ruta/pdfs -o /ruta/salida",
    )

    parser.add_argument(
        "input_path",
        help="Ruta a un archivo PDF o a un directorio con PDFs",
    )

    parser.add_argument(
        "-o",
        "--output-dir",
        dest="output_dir",
        help="Directorio de salida para los Excel generados. "
        "Si no se especifica, se usa el mismo directorio del PDF.",
    )

    return parser.parse_args()


if __name__ == "__main__":
    main()
