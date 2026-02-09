"""
Decodificador EBCDIC para PDFs de HSBC.

¿Por qué existe este módulo?
Los estados de cuenta de HSBC México usan un font encoding personalizado
(similar a EBCDIC CP500) que hace que pdfplumber extraiga texto garbled:
- "ˆ(cid:228)¯(cid:213)ª`@(cid:201)(cid:213)ª¯˙(cid:217)`(cid:211)" → "CUENTA INTEGRAL"
- "(cid:244)(cid:240)(cid:240)(cid:247)æłıł(cid:240)(cid:244)" → "4007185804"

Este mapeo fue construido empíricamente comparando el texto renderizado
visualmente (imágenes del PDF) vs el texto extraído por pdfplumber.

La alternativa sería usar OCR (pytesseract), que es lo que hacía el
script original, pero la decodificación directa es:
- 100x más rápida (no requiere conversión a imagen ni OCR).
- Más precisa (no hay errores de reconocimiento óptico).
- No requiere dependencias externas (tesseract, poppler).
"""

# Mapeo completo EBCDIC CID → ASCII
# Construido empíricamente desde un PDF real de HSBC México (nov 2025).
# Cada entrada mapea un carácter (o token CID) al carácter ASCII correcto.
_CHAR_MAP: dict[str, str] = {
    # ── Espacio ──
    "@": " ",
    # ── Puntuación y símbolos ──
    "K": ".",
    "k": ",",
    "a": "/",
    "[": "$",
    "]": ")",
    "M": "(",
    "l": "%",
    "z": ":",
    "N": "+",
    "O": "*",
    # ── Letras mayúsculas (EBCDIC C1-E9) ──
    "`": "A",
    "\u00b4": "B",  # ´
    "\u02c6": "C",  # ˆ
    "\u02dc": "D",  # ˜
    "\u00af": "E",  # ¯
    "\u02d8": "F",  # ˘
    "\u02d9": "G",  # ˙
    "\u00a8": "H",  # ¨
    "(cid:201)": "I",
    "(cid:209)": "J",
    "(cid:210)": "K",
    "(cid:211)": "L",
    "(cid:212)": "M",
    "(cid:213)": "N",
    "(cid:214)": "O",
    "(cid:215)": "P",
    "(cid:216)": "Q",
    "(cid:217)": "R",
    "(cid:226)": "S",
    "\u00aa": "T",  # ª
    "(cid:228)": "U",
    "(cid:229)": "V",
    "(cid:230)": "W",
    "(cid:231)": "X",
    "(cid:232)": "Y",
    "(cid:233)": "Z",
    # ── Letras minúsculas (EBCDIC 81-A5) ──
    "(cid:129)": "a",
    "(cid:130)": "b",
    "(cid:131)": "c",
    "(cid:132)": "d",
    "(cid:133)": "e",
    "(cid:134)": "f",
    "(cid:135)": "g",
    "(cid:136)": "h",
    "(cid:137)": "i",
    "(cid:145)": "j",
    "(cid:146)": "k",
    "(cid:147)": "l",
    "(cid:148)": "m",
    "(cid:149)": "n",
    "(cid:150)": "o",
    "(cid:151)": "p",
    "(cid:152)": "q",
    "(cid:153)": "r",
    "\u00a2": "s",  # ¢
    "\u00a3": "t",  # £
    "\u2044": "u",  # ⁄
    "\u00a5": "v",  # ¥
    "\u0192": "w",  # ƒ
    # ── Dígitos (EBCDIC F0-F9) ──
    "(cid:240)": "0",
    "\u00e6": "1",  # æ
    "(cid:242)": "2",
    "(cid:243)": "3",
    "(cid:244)": "4",
    "\u0131": "5",  # ı (dotless i)
    "(cid:246)": "6",
    "(cid:247)": "7",
    "\u0142": "8",  # ł (Polish L)
    "\u00f8": "9",  # ø
    # ── Caracteres especiales del español ──
    "(cid:238)": "\u00d1",  # Ñ
    "\u02db": "\u00f3",  # ó  (˛)
    "(cid:254)": "\u00fa",  # ú
    "(cid:222)": "\u00fa",  # ú (variante mayúscula)
    "(cid:190)": "'",
    # ── Guiones y variantes ──
    "\u2019": "-",
    "\u2018": "-",
    "\u203a": "-",
    "\u00c6": "-",
}


def needs_ebcdic_decoding(text: str) -> bool:
    """Detecta si el texto requiere decodificación EBCDIC.

    Los PDFs de HSBC México usan un font encoding personalizado que
    produce tokens "(cid:NNN)" cuando pdfplumber extrae el texto.
    Si el texto NO contiene estos tokens, ya está limpio y NO debe
    pasar por el decodificador (porque el mapeo corrompe caracteres
    normales: 'a' → '/', 'l' → '%', 'K' → '.', etc.).

    Args:
        text: Texto tal como lo extrae pdfplumber.

    Returns:
        True si contiene tokens CID (necesita decodificación).
        False si el texto ya está limpio.
    """
    return "(cid:" in text


def decode_hsbc_text(encoded: str) -> str:
    """Decodifica texto EBCDIC de un PDF de HSBC a texto legible.

    Maneja dos tipos de tokens:
    1. Tokens CID: "(cid:NNN)" — referencias a glifos del font personalizado.
    2. Caracteres Unicode individuales mapeados a EBCDIC.

    Args:
        encoded: Texto tal como lo extrae pdfplumber del PDF de HSBC.

    Returns:
        Texto decodificado legible en español.

    Ejemplo:
        >>> decode_hsbc_text("ˆ(cid:228)¯(cid:213)ª`@(cid:201)(cid:213)ª¯˙(cid:217)`(cid:211)")
        'CUENTA INTEGRAL'
    """
    result: list[str] = []
    i = 0
    length = len(encoded)

    while i < length:
        # Detectar tokens (cid:NNN)
        if encoded[i : i + 5] == "(cid:":
            end = encoded.find(")", i + 5)
            if end != -1:
                token = encoded[i : end + 1]
                result.append(_CHAR_MAP.get(token, token))
                i = end + 1
                continue

        # Carácter individual
        ch = encoded[i]
        if ch == "\n":
            result.append("\n")
        else:
            result.append(_CHAR_MAP.get(ch, ch))
        i += 1

    return "".join(result)
