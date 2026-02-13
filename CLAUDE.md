# Bank Statement Parser - Instrucciones para Claude Code

## Descripcion del proyecto

Herramienta CLI en Python que extrae y consolida estados de cuenta bancarios de PDFs mexicanos a archivos Excel estandarizados. Soporta PDFs nativos, escaneados (OCR), cifrados y mixtos.

**Comando CLI:** `bank-parser /ruta/pdfs -o /ruta/salida`

## Arquitectura

El proyecto usa **arquitectura hexagonal (puertos y adaptadores)**:

```
src/
├── domain/              # Logica de negocio (NO depende de librerias externas)
│   ├── models/          # Entidades inmutables (frozen dataclasses)
│   ├── ports/           # Interfaces abstractas (ABC)
│   ├── services/        # Orquestador (StatementProcessor)
│   ├── shared/          # Utilidades de dominio (money, dates, text)
│   └── exceptions.py    # Jerarquia de excepciones
├── adapters/            # Implementaciones concretas
│   ├── input/
│   │   ├── text_extractors/   # PdfplumberExtractor, OcrExtractor
│   │   ├── bank_identifiers/  # KeywordBankIdentifier
│   │   └── bank_parsers/      # Un parser por banco (BBVA, Banorte, etc.)
│   └── output/
│       ├── writers/           # ExcelWriter
│       └── loggers/           # ConsoleLogger
├── infrastructure/
│   └── registry.py      # BankParserRegistry (DI container)
└── cli/
    └── main.py          # Punto de entrada (solo wiring, cero logica)
```

## Gitflow

Este proyecto sigue **gitflow estricto**:

- **main**: Rama estable. Solo recibe merges desde `develop` via PR.
- **develop**: Rama de integracion. Las features se mergean aqui.
- **feature/***: Ramas de trabajo. Se crean desde `develop`.
- **fix/***: Correcciones. Se crean desde `develop`.

**REGLAS:**
- NUNCA hacer commit directo a `main` o `develop`
- SIEMPRE crear una rama `feature/*` o `fix/*` desde `develop`
- SIEMPRE crear PR para mergear a `develop`
- Los pre-commit hooks bloquean commits directos a `main`/`develop`

## Convenciones de codigo

- **Docstrings y comentarios**: en espanol
- **Nombres de variables/funciones/clases**: en ingles (snake_case, PascalCase)
- **Line length**: 100 caracteres
- **Python**: 3.11+
- **Type hints**: se usan pero no se exigen al 100% (mypy permisivo)
- **Montos**: SIEMPRE usar `Decimal`, NUNCA `float`
- **Modelos**: SIEMPRE `frozen=True` en dataclasses de dominio
- **Imports**: ordenados por ruff (isort compatible)

## Como agregar un nuevo banco

Para agregar soporte de un nuevo banco se requieren **4 archivos**:

1. **Parser** en `src/adapters/input/bank_parsers/{banco}_parser.py`
   - Implementar la interfaz `BankParser` (ver `src/domain/ports/bank_parser.py`)
   - Propiedad `bank_name` → nombre en MAYUSCULAS
   - Metodo `parse(pages: list[PageText], file_name: str) -> ResultadoParseo`

2. **Keywords** en `src/adapters/input/bank_identifiers/keyword_identifier.py`
   - Agregar tupla `("NOMBRE_BANCO", ["keyword1", "keyword2"])` a `_BANK_KEYWORDS`
   - Ordenar de mas especifico a mas generico

3. **Registro** en `src/infrastructure/registry.py`
   - Importar el parser en `create_default_registry()`
   - Llamar `registry.register(NuevoBancoParser())`

4. **Tests** en `tests/unit/adapters/test_{banco}_parser.py`
   - Tests unitarios con texto de ejemplo (no PDFs reales)
   - Verificar: info_cuenta, movimientos, resumen

## Comandos de desarrollo

```bash
make install     # Instalar dependencias (dev + OCR)
make test        # Tests unitarios solamente
make test-all    # Todos los tests (incluye integracion)
make lint        # Verificar estilo (ruff + mypy, sin modificar)
make format      # Auto-formatear codigo (ruff + black)
make check       # lint + test (gate de CI)
make clean       # Limpiar caches
```

## Patrones importantes

- **Dependency Injection**: `StatementProcessor` recibe todas sus dependencias por constructor
- **Strategy Pattern**: Multiples extractores/parsers seleccionados en runtime
- **Registry Pattern**: `BankParserRegistry` mapea nombre_banco → parser
- **Hybrid PDF**: El procesador intenta pdfplumber primero, luego OCR para paginas vacias, y mergea resultados
- **Position-based parsing**: BBVA y Banorte usan coordenadas X/Y de palabras (requiere `include_words=True` en pdfplumber)
- **Regex-based parsing**: Santander, Scotiabank, VantageBank, HSBC usan regex sobre lineas de texto

## Skills disponibles

El proyecto incluye skills personalizados en `.claude/skills/`. Se invocan escribiendo `/nombre` en el chat de Claude Code.

| Skill | Invocacion | Descripcion |
|-------|-----------|-------------|
| **add-bank** | `/add-bank citibanamex` | Scaffold completo para un nuevo banco: parser, keywords, registro y tests. Crea la rama feature automaticamente. |
| **test** | `/test` | Ejecuta tests unitarios. Acepta `--all` (integracion), `--cov` (cobertura) o una ruta especifica. |
| **lint** | `/lint` | Ejecuta ruff + mypy. Si hay errores de formato, auto-corrige con `make format`. |
| **new-feature** | `/new-feature parser-monex` | Crea una rama `feature/{nombre}` desde `develop` siguiendo gitflow. |
| **pr** | `/pr` | Crea un Pull Request a `develop`: ejecuta verificaciones, genera titulo/descripcion, y lo publica con `gh`. |
| **parse-test** | `/parse-test Data/5-Mayo/` | Prueba el parser contra un PDF o directorio real y analiza el resultado. |

### Auto-invocacion

Algunos skills se activan automaticamente cuando Claude Code detecta que son relevantes para la tarea:

- **add-bank**: Si pides "agrega soporte para Monex", Claude invoca este skill sin necesidad de escribir `/add-bank`.
- **parse-test**: Si pides "prueba el parser con este PDF", Claude lo detecta y ejecuta el skill.

Los demas skills tienen `disable-model-invocation: true` porque ejecutan acciones con efectos secundarios (git, PR, formateo). Para usarlos debes invocarlos explicitamente con `/nombre`.

### Ejemplo de flujo completo

```
/new-feature parser-citibanamex       # Crear rama feature
/add-bank citibanamex                 # Generar scaffold del banco
# ... implementar logica de parseo ...
/parse-test Data/5-Mayo/citi.pdf      # Probar con un PDF real
/test --all                           # Verificar todos los tests
/lint                                 # Verificar estilo
/pr                                   # Crear PR a develop
```

## Bancos implementados

BBVA, Banorte, Santander, Scotiabank, VantageBank, HSBC

## Bancos pendientes

Citibanamex, Citi, Monex, Sabadell, Banregio, Inbursa, Intercam, Bankaool, Bank of America, JP Morgan, BX+
