# Bank Statement Parser

Extractor y consolidador de estados de cuenta bancarios mexicanos. Parsea PDFs de múltiples bancos y genera un Excel consolidado con un layout estandarizado.

## Bancos Soportados

BBVA · Banorte · Citibanamex · Citi · Santander · Scotiabank · Monex · Sabadell · Banregio · Inbursa · Intercam · Bankaool · Bank of America · Vantage Bank · JP Morgan · BX+

## Tipos de PDF Soportados

- **Nativo** — Texto embebido (BBVA, Banorte, etc.)
- **Nativo parcial** — Texto parcialmente embebido (Citibanamex)
- **Bloqueado** — Protegido contra copiar/pegar (Monex) → se procesa con OCR
- **Escaneado** — Imagen escaneada → se procesa con OCR (Tesseract)
- **Cifrado** — Caracteres sustituidos (HSBC, JP Morgan) → se aplica mapeo de caracteres

## Requisitos

- Python 3.11+
- Para OCR: [Tesseract](https://github.com/tesseract-ocr/tesseract) + [Poppler](https://poppler.freedesktop.org/)

## Instalación

```bash
# Clonar el repositorio
git clone https://github.com/carlossalinas17/parser_bank.git
cd parser_bank

# Instalar en modo desarrollo (incluye herramientas de lint y test)
make install

# Solo dependencias de producción
pip install -e .

# Con soporte OCR
pip install -e ".[ocr]"
```

## Uso

```bash
# Procesar una carpeta con PDFs
bank-parser /ruta/a/pdfs -o /ruta/salida

# Procesar un solo PDF
bank-parser /ruta/estado_bbva.pdf -o /ruta/salida
```

## Desarrollo

```bash
make test        # Ejecutar tests unitarios
make lint        # Verificar estilo y tipos
make format      # Formatear código
make check       # lint + test (lo que hace el CI)
```

## Arquitectura

El proyecto usa **Arquitectura Hexagonal (Ports & Adapters)**:

```
src/
├── domain/          # Modelos, puertos (interfaces), servicios, utilidades
├── adapters/        # Implementaciones: extractores, parsers, writers, loggers
├── infrastructure/  # Configuración, inyección de dependencias, registro
└── cli/             # Punto de entrada CLI
```

Ver [analisis_arquitectura.md](./docs/analisis_arquitectura.md) para la documentación detallada de la arquitectura.

## Branching Strategy

- `main` — Releases estables. Solo merges desde `develop` vía PR.
- `develop` — Integración continua. Merges desde feature branches.
- `feature/*` — Una rama por funcionalidad. Ejemplo: `feature/bbva-parser`.

## Layout de Salida (Excel)

**Hoja 1 — Resumen:** Totales de depósitos y retiros por cuenta.

**Hoja 2 — Movimientos:**

| Banco | Cuenta | Moneda | Fecha | Fecha.1 | Concepto | Referencia | Retiros | Depósitos |
|-------|--------|--------|-------|---------|----------|------------|---------|-----------|

## Licencia

Propietario — Uso interno.
