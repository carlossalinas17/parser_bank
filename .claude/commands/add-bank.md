# Skill: Agregar soporte para un nuevo banco

Vas a agregar soporte completo para el banco: **$ARGUMENTS**

## Pasos a seguir

### 1. Crear rama feature
- Verifica que exista la rama `develop`. Si no estas en ella, haz checkout.
- Crea la rama `feature/parser-{nombre_banco_lowercase}` desde `develop`.

### 2. Crear el parser
Crea el archivo `src/adapters/input/bank_parsers/{nombre_banco_lowercase}_parser.py`.

Debe implementar la interfaz `BankParser` de `src/domain/ports/bank_parser.py`:
- Propiedad `bank_name` que retorne el nombre en MAYUSCULAS
- Metodo `parse(pages: list[PageText], file_name: str) -> ResultadoParseo`

Usa como referencia los parsers existentes en `src/adapters/input/bank_parsers/`.
- Si el banco usa texto plano (la mayoria), sigue el patron de `santander_parser.py` (regex sobre lineas).
- Si el banco requiere coordenadas X/Y, sigue el patron de `bbva_parser.py` (posicion de palabras).

El parser debe:
- Extraer info de cuenta (banco, numero de cuenta, moneda)
- Extraer movimientos (fecha, concepto, referencia, retiro/deposito)
- Calcular resumen (total retiros, total depositos, saldo)
- Usar `Decimal` para todos los montos (NUNCA float)
- Usar las utilidades compartidas: `parse_money_safe()`, `MONTH_MAP`, `DateParser`
- Lanzar `ParseError` con contexto si hay errores

Incluye un docstring en espanol explicando la logica de parseo del banco.

### 3. Agregar keywords de identificacion
En `src/adapters/input/bank_identifiers/keyword_identifier.py`:
- Agrega una tupla `("NOMBRE_BANCO", ["keyword1", "keyword2", ...])` a `_BANK_KEYWORDS`
- Las keywords deben ser textos que aparecen en los estados de cuenta de ese banco
- Ordena de mas especifico a mas generico

### 4. Registrar el parser
En `src/infrastructure/registry.py`, dentro de `create_default_registry()`:
- Importa el nuevo parser
- Registralo con `registry.register(NuevoBancoParser())`

### 5. Crear tests unitarios
Crea `tests/unit/adapters/test_{nombre_banco_lowercase}_parser.py`.

Sigue el patron de los tests existentes (ej: `test_santander_parser.py`):
- Crea texto de ejemplo que simule un estado de cuenta del banco
- Construye objetos `PageText` con ese texto
- Verifica que `parse()` retorne un `ResultadoParseo` correcto
- Verifica info_cuenta, al menos un movimiento, y el resumen

### 6. Verificar
Ejecuta `make check` (lint + tests) y corrige cualquier error.

### 7. Resumen
Al finalizar, muestra:
- Archivos creados/modificados
- Numero de tests agregados
- Estado del `make check`
- Instrucciones para el siguiente paso (implementar logica de parseo especifica si se dejo como scaffold)
