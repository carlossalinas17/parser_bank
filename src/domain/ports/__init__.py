"""
Puertos (interfaces) del dominio.

Los puertos definen QUÉ necesita el dominio, sin decir CÓMO se implementa.
Cada puerto tiene uno o más adaptadores que lo implementan.

Uso:
    from src.domain.ports import TextExtractor, BankParser, OutputWriter
"""

from src.domain.ports.bank_identifier import BankIdentifier
from src.domain.ports.bank_parser import BankParser
from src.domain.ports.output_writer import OutputWriter
from src.domain.ports.process_logger import ProcessLogger
from src.domain.ports.text_extractor import TextExtractor

__all__ = [
    "BankIdentifier",
    "BankParser",
    "OutputWriter",
    "ProcessLogger",
    "TextExtractor",
]
