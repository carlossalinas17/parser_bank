# =============================================================================
# Makefile — Comandos de conveniencia para bank-statement-parser
#
# USO:
#   make install      → Instala el proyecto en modo desarrollo
#   make test         → Ejecuta todos los tests
#   make lint         → Verifica estilo y tipos
#   make format       → Formatea el código automáticamente
#   make check        → Ejecuta lint + test (lo que hace el CI)
#   make clean        → Limpia archivos temporales
# =============================================================================

.PHONY: install test lint format check clean help

# --- Variables ---
PYTHON := python3
PIP := pip

# --- Comandos principales ---

## Instala el proyecto con todas las dependencias de desarrollo.
## Es lo primero que debe ejecutar cualquier persona que clone el repo.
## El flag -e hace "editable install": los cambios en src/ se reflejan
## inmediatamente sin reinstalar.
install:
	$(PIP) install -e ".[dev,ocr]" --break-system-packages
	pre-commit install

## Ejecuta todos los tests unitarios y muestra cobertura.
## Los tests de integración (marcados con @pytest.mark.integration)
## se excluyen por defecto porque requieren PDFs reales.
test:
	pytest tests/ -v --cov=src --cov-report=term-missing -m "not integration"

## Ejecuta TODOS los tests, incluyendo integración.
## Usar cuando se tiene acceso a los PDFs de prueba.
test-all:
	pytest tests/ -v --cov=src --cov-report=term-missing

## Verifica estilo de código (ruff), formato (black --check), y tipos (mypy).
## No modifica ningún archivo; solo reporta errores.
## Esto es exactamente lo que ejecuta el CI en cada PR.
lint:
	ruff check src/ tests/
	black --check src/ tests/
	mypy src/

## Formatea el código automáticamente.
## Ejecutar ANTES de hacer commit para evitar que el CI falle.
format:
	ruff check --fix src/ tests/
	black src/ tests/

## Ejecuta lint + test. Es el "gate" completo antes de hacer push.
## Si este comando pasa, el CI también debería pasar.
check: lint test

## Limpia archivos temporales generados por Python, pytest y build.
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "dist" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "build" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .coverage htmlcov/

## Muestra esta ayuda.
help:
	@echo "Comandos disponibles:"
	@echo "  make install   → Instala el proyecto en modo desarrollo"
	@echo "  make test      → Ejecuta tests unitarios con cobertura"
	@echo "  make test-all  → Ejecuta TODOS los tests (incluye integración)"
	@echo "  make lint      → Verifica estilo, formato y tipos"
	@echo "  make format    → Formatea código automáticamente"
	@echo "  make check     → lint + test (lo que hace el CI)"
	@echo "  make clean     → Limpia archivos temporales"
