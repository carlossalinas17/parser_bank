---
name: pr
description: Crea un Pull Request de la rama actual hacia develop con verificaciones automaticas y descripcion generada.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash, Read, Grep, Glob
---

# Skill: Crear Pull Request

Crea un Pull Request de la rama actual hacia `develop`.

## Pasos

### 1. Verificar prerequisitos
- Verifica que NO estamos en `main` ni en `develop`.
- Ejecuta `git status` para verificar que no hay cambios sin commitear.
- Si hay cambios pendientes, pregunta si quieres commitearlos primero.

### 2. Ejecutar verificaciones
- Ejecuta `make check` (lint + tests).
- Si falla, muestra los errores y pregunta si quieres continuar de todos modos.

### 3. Analizar cambios
- Ejecuta `git log develop..HEAD --oneline` para ver los commits de la rama.
- Ejecuta `git diff develop...HEAD --stat` para ver los archivos cambiados.

### 4. Generar PR
- Genera un titulo conciso (max 70 caracteres) basado en los commits.
- Genera una descripcion con:
  - Resumen de cambios (bullet points)
  - Archivos principales modificados
  - Plan de pruebas

### 5. Crear el PR
- Push la rama al remoto: `git push -u origin {rama_actual}`
- Crea el PR: `gh pr create --base develop --title "..." --body "..."`

### 6. Confirmar
Muestra la URL del PR creado.
