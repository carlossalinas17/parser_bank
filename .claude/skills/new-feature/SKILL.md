---
name: new-feature
description: Crea una nueva rama feature desde develop siguiendo la metodologia gitflow del proyecto.
argument-hint: [descripcion-de-la-feature]
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash
---

# Skill: Crear rama feature (gitflow)

Crea una nueva rama feature siguiendo gitflow para: **$ARGUMENTS**

## Pasos

### 1. Validar estado del repositorio
- Ejecuta `git status` para verificar que no hay cambios sin commitear.
- Si hay cambios pendientes, advierte al usuario y pregunta si quiere hacer stash.

### 2. Actualizar develop
- Ejecuta `git checkout develop`
- Ejecuta `git pull origin develop` (si existe el remoto)

### 3. Crear la rama feature
- Normaliza el nombre: convierte `$ARGUMENTS` a kebab-case lowercase (sin acentos, sin caracteres especiales).
- Crea la rama: `git checkout -b feature/{nombre-normalizado}`

### 4. Confirmar
Muestra:
- Nombre de la rama creada
- Rama base (develop)
- Estado del repositorio (`git status`)
- Recordatorio: "Cuando termines, usa `/pr` para crear el Pull Request a develop"
