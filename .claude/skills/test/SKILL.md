---
name: test
description: Ejecuta los tests del proyecto de forma inteligente. Soporta tests unitarios, de integracion y con cobertura.
argument-hint: [--all | --cov | ruta/archivo]
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash, Read, Grep
---

# Skill: Ejecutar tests

Ejecuta los tests del proyecto segun los argumentos proporcionados: **$ARGUMENTS**

## Logica

1. Si `$ARGUMENTS` esta vacio o no se proporcionaron argumentos:
   - Ejecuta: `make test` (solo tests unitarios, excluye integracion)

2. Si `$ARGUMENTS` contiene `--all`:
   - Ejecuta: `make test-all` (todos los tests, incluye integracion)

3. Si `$ARGUMENTS` contiene `--cov`:
   - Ejecuta: `pytest --cov=src --cov-report=term-missing tests/unit/`

4. Si `$ARGUMENTS` contiene una ruta o nombre de archivo especifico:
   - Ejecuta: `pytest {ruta_especificada} -v`

## Despues de ejecutar

- Si todos los tests pasan: muestra un resumen con el numero de tests ejecutados.
- Si hay tests fallidos:
  1. Muestra cuales fallaron y por que.
  2. Analiza el error y sugiere una correccion concreta.
  3. Pregunta si quieres que aplique la correccion automaticamente.
