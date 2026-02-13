# Skill: Linting y formateo

Ejecuta las herramientas de calidad de codigo del proyecto.

## Pasos

### 1. Verificar (sin modificar)
Ejecuta `make lint` que incluye:
- `ruff check src/ tests/` (linter)
- `mypy src/` (type checking)

### 2. Si hay errores de formato
Ejecuta `make format` para auto-corregir lo que se pueda:
- `ruff check --fix src/ tests/`
- `ruff format src/ tests/`
- `black src/ tests/`

### 3. Reportar
- Si todo paso limpio: confirma que el codigo cumple los estandares.
- Si quedaron errores que no se pudieron auto-corregir:
  1. Lista cada error con archivo y linea.
  2. Sugiere la correccion para cada uno.
  3. Pregunta si quieres que aplique las correcciones.
