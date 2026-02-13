#!/bin/bash
# Hook: Auto-formatear archivos Python despues de Edit/Write
#
# Recibe JSON por stdin con la informacion del tool use.
# Extrae el file_path y ejecuta ruff si es un .py

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Sin ruta, nada que hacer
if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Solo archivos Python
if [[ "$FILE_PATH" != *.py ]]; then
  exit 0
fi

# Auto-fix y formato (exit 0 para no bloquear a Claude)
ruff check --fix "$FILE_PATH" 2>&1 || true
ruff format "$FILE_PATH" 2>&1 || true

exit 0
