"""
Registro de bank parsers disponibles.

Centraliza la relación nombre_banco → parser_instance.
Agregar un nuevo banco al sistema requiere solo 2 pasos:
1. Crear la clase XxxParser que implemente BankParser.
2. Registrarla aquí con register() o agregarla a _register_defaults().

¿Por qué un registro separado y no hardcodear en el orquestador?
Porque el orquestador no debe saber qué bancos existen. Solo pide
"dame el parser para BBVA" y el registro se lo da. Esto cumple el
principio Open/Closed: agregar banco = agregar código, no modificar.
"""

from src.domain.ports.bank_parser import BankParser


class BankParserRegistry:
    """Registro de parsers de bancos disponibles."""

    def __init__(self) -> None:
        self._parsers: dict[str, BankParser] = {}

    def register(self, parser: BankParser) -> None:
        """Registra un parser. La clave es parser.bank_name (mayúsculas).

        Args:
            parser: Instancia de un BankParser concreto.

        Raises:
            ValueError: Si ya existe un parser para ese banco.
        """
        name = parser.bank_name.upper()
        if name in self._parsers:
            raise ValueError(
                f"Ya existe un parser registrado para '{name}': "
                f"{type(self._parsers[name]).__name__}. "
                f"No se puede registrar {type(parser).__name__}."
            )
        self._parsers[name] = parser

    def get(self, bank_name: str) -> BankParser | None:
        """Obtiene el parser para un banco.

        Args:
            bank_name: Nombre del banco (case-insensitive).

        Returns:
            BankParser si existe, None si no hay parser para ese banco.
        """
        return self._parsers.get(bank_name.upper())

    @property
    def available_banks(self) -> list[str]:
        """Lista de bancos con parser disponible."""
        return sorted(self._parsers.keys())

    def __len__(self) -> int:
        return len(self._parsers)


def create_default_registry() -> BankParserRegistry:
    """Crea un registro con todos los parsers disponibles.

    Esta función es el punto donde se registran todos los bancos.
    Conforme se migran más bancos, se agregan aquí.

    Returns:
        BankParserRegistry con todos los parsers registrados.
    """
    registry = BankParserRegistry()

    # --- Importar y registrar parsers disponibles ---
    # Se importan aquí (no al inicio del archivo) para que si un parser
    # tiene un error de importación, no rompa todo el registro.

    from src.adapters.input.bank_parsers.bbva_parser import BBVAParser

    registry.register(BBVAParser())

    from src.adapters.input.bank_parsers.banorte_parser import BanorteParser

    registry.register(BanorteParser())

    from src.adapters.input.bank_parsers.santander_parser import SantanderParser

    registry.register(SantanderParser())

    from src.adapters.input.bank_parsers.scotiabank_parser import ScotiabankParser

    registry.register(ScotiabankParser())

    from src.adapters.input.bank_parsers.vantagebank_parser import VantageBankParser

    registry.register(VantageBankParser())

    # Conforme se migren más bancos, se agregan aquí:
    # from src.adapters.input.bank_parsers.banorte_parser import BanorteParser
    # registry.register(BanorteParser())
    #
    # from src.adapters.input.bank_parsers.citibanamex_parser import CitibanamexParser
    # registry.register(CitibanamexParser())

    return registry
