"""
Adaptador de entrada: Identificador de banco por keywords.

Busca términos clave en el texto de las primeras páginas del PDF para
determinar a qué banco corresponde el estado de cuenta.

¿Por qué keywords y no algo más sofisticado (ML, NLP)?
Porque los estados de cuenta bancarios tienen textos muy predecibles:
siempre incluyen el nombre del banco, dirección corporativa, o RFC.
Un simple string matching tiene ~99% de acierto y es instantáneo.

Las keywords se ordenan por especificidad: primero las más específicas
(como "BANCOMER" que solo es BBVA) y al final las más genéricas.
"""

from src.domain.ports.bank_identifier import BankIdentifier


class KeywordBankIdentifier(BankIdentifier):
    """Identifica bancos por keywords en el texto del estado de cuenta.

    Las keywords están organizadas como una lista de tuplas
    (nombre_banco, [keywords]). El orden importa: se evalúan de
    arriba a abajo y gana la primera coincidencia.

    ¿Por qué una lista y no un diccionario?
    Porque el orden de evaluación importa. Si un texto contiene
    "BBVA" y "BANCOMER", ambos matchean BBVA, pero queremos que
    "BANCOMER" tenga prioridad sobre un hipotético "BANCA" genérico.
    """

    # Cada tupla: (nombre_normalizado, [keywords que lo identifican])
    # Las keywords son CASE-INSENSITIVE (se buscan en texto.upper()).
    # Se usan múltiples keywords por banco porque el formato del PDF
    # varía entre periodos y sucursales.
    _BANK_KEYWORDS: list[tuple[str, list[str]]] = [
        # --- Bancos mexicanos ---
        (
            "BBVA",
            [
                "BBVA BANCOMER",
                "BBVA MEXICO",
                "BBVA MÉXICO",
                "BANCOMER",
                # Último porque "BBVA" podría aparecer como referencia en
                # otros bancos (ej: "TRANSFERENCIA A BBVA")
                "BBVA",
            ],
        ),
        (
            "BANORTE",
            [
                "BANCO MERCANTIL DEL NORTE",
                "BANORTE",
                # Productos exclusivos de Banorte — algunos estados de cuenta
                # NO dicen "BANORTE" en el encabezado, solo el nombre del producto.
                "ENLACE GLOBAL",
                "ENLACE NEGOCIOS",
            ],
        ),
        (
            "CITIBANAMEX",
            [
                "CITIBANAMEX",
                "BANAMEX",
                "BANCO NACIONAL DE MEXICO",
                "BANCO NACIONAL DE MÉXICO",
            ],
        ),
        (
            "CITI",
            [
                # Importante: evaluar DESPUÉS de CITIBANAMEX para que
                # "CITIBANAMEX" no matchee como "CITI".
                "CITIBANK",
                "CITI BANK",
            ],
        ),
        (
            "SANTANDER",
            [
                "SANTANDER",
                "BANCO SANTANDER",
            ],
        ),
        (
            "SCOTIABANK",
            [
                "SCOTIABANK",
                "SCOTIA",
            ],
        ),
        (
            "MONEX",
            [
                "BANCO MONEX",
                "MONEX",
            ],
        ),
        (
            "SABADELL",
            [
                "BANCO SABADELL",
                "SABADELL",
            ],
        ),
        (
            "BANREGIO",
            [
                "BANREGIO",
                "BANCO REGIONAL",
            ],
        ),
        (
            "INBURSA",
            [
                "INBURSA",
                "BANCO INBURSA",
            ],
        ),
        (
            "INTERCAM",
            [
                "INTERCAM",
                "BANCO INTERCAM",
            ],
        ),
        (
            "BANKAOOL",
            [
                "BANKAOOL",
            ],
        ),
        # --- Bancos internacionales ---
        (
            "BANK_OF_AMERICA",
            [
                "BANK OF AMERICA",
            ],
        ),
        (
            "VANTAGE_BANK",
            [
                "VANTAGE BANK",
                "VANTAGE",
            ],
        ),
        (
            "JP_MORGAN",
            [
                "J.P. MORGAN",
                "JPMORGAN",
                "JP MORGAN",
            ],
        ),
        (
            "BX_PLUS",
            [
                "BX+",
                "BANCO VE POR MÁS",
                "BANCO VE POR MAS",
            ],
        ),
    ]

    def identify(self, text: str) -> str | None:
        """Identifica el banco buscando keywords en el texto.

        Estrategia de búsqueda en dos fases:
        1. Primero busca en el ENCABEZADO (primeras 20 líneas).
           Aquí siempre está el nombre institucional del banco.
        2. Si no encuentra nada, busca en todo el texto.

        ¿Por qué dos fases?
        Porque los movimientos mencionan otros bancos ("TRANSFERENCIA A BBVA",
        "PAGO SANTANDER", "SPEI BANAMEX") y si buscamos en todo el texto,
        esas menciones pueden matchear antes que el banco correcto.
        El encabezado es la fuente más confiable.

        Args:
            text: Texto de las primeras páginas del PDF.

        Returns:
            Nombre normalizado del banco (ej: "BBVA", "BANORTE") o None.
        """
        # Fase 1: buscar solo en el encabezado (primeras 20 líneas)
        lineas = text.split("\n")
        encabezado = "\n".join(lineas[:20]).upper()

        for bank_name, keywords in self._BANK_KEYWORDS:
            for keyword in keywords:
                if keyword.upper() in encabezado:
                    return bank_name

        # Fase 2: si no se encontró en el encabezado, buscar en todo el texto
        text_upper = text.upper()

        for bank_name, keywords in self._BANK_KEYWORDS:
            for keyword in keywords:
                if keyword.upper() in text_upper:
                    return bank_name

        return None

    @property
    def supported_banks(self) -> list[str]:
        """Lista de bancos soportados. Útil para logging y debugging."""
        return [name for name, _ in self._BANK_KEYWORDS]
