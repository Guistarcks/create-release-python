# GitHub Actions Workflows

Este directorio contiene workflows reutilizables para automatizar procesos de CI/CD.

## Workflows Disponibles

### 1. action-build.yml
Acción reutilizable para construir proyectos Node.js.

#### Parámetros de entrada:
- `node-version` (requerido): Versión de Node.js a usar
- `build-command` (opcional): Comando de build a ejecutar (default: 'npm run build')
- `artifact-name` (opcional): Nombre para los artefactos subidos (default: 'node-app-artifacts')
- `artifact-path` (opcional): Ruta a subir como artefactos (default: '.')
- `retention-days` (opcional): Días de retención de artefactos (default: 7)

#### Ejemplo de uso:
```yaml
jobs:
  build:
    uses: ./.github/workflows/action-build.yml
    with:
      node-version: '18'
      build-command: 'npm run build'
      artifact-name: 'my-app-build'
      artifact-path: './dist'
      retention-days: 14
```

### 2. action-sonar.yml
Acción reutilizable para análisis de calidad con SonarQube.

#### Parámetros de entrada:
- `node-version` (requerido): Versión de Node.js a usar
- `java-version` (opcional): Versión de Java para SonarQube (default: '17')
- `coverage-artifact-name` (opcional): Nombre del artefacto de cobertura (default: 'coverage-reports')
- `coverage-path` (opcional): Ruta donde están los reportes de cobertura (default: 'coverage/')
- `project-key` (requerido): Clave del proyecto en SonarQube
- `project-name` (requerido): Nombre del proyecto en SonarQube
- `sonar-host-url` (requerido): URL del servidor SonarQube
- `sources-path` (opcional): Ruta del código fuente (default: '.')
- `exclusions` (opcional): Archivos a excluir del análisis (default: '**/*.java')
- `coverage-exclusions` (opcional): Archivos a excluir de cobertura (default: '**/*.test.js,**/*.spec.js,**/node_modules/**')
- `lcov-report-path` (opcional): Ruta al archivo lcov.info (default: 'coverage/lcov.info')

#### Secretos requeridos:
- `SONAR_TOKEN` (requerido): Token de autenticación de SonarQube

#### Ejemplo de uso:
```yaml
jobs:
  sonar:
    uses: ./.github/workflows/action-sonar.yml
    with:
      node-version: '18'
      java-version: '17'
      project-key: 'my-project'
      project-name: 'My Project'
      sonar-host-url: 'https://sonar.example.com'
      coverage-artifact-name: 'coverage-reports'
      coverage-path: 'coverage/'
    secrets:
      SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

### 3. action-deploy-pre.yml
Acción para deploy en pre-producción.

### 4. action-deploy-pro.yml
Acción para deploy en producción.

### 5. test-unitarios.yml
Workflow principal que ejecuta tests, análisis de calidad y build.

## Uso de las Acciones

### Acción de Build

La acción de build está diseñada para ser flexible y reutilizable:

#### Casos de uso comunes:

1. **Proyecto React:**
```yaml
build-react:
  uses: ./.github/workflows/action-build.yml
  with:
    node-version: '18'
    build-command: 'npm run build'
    artifact-name: 'react-app-build'
    artifact-path: './build'
```

2. **Proyecto Vue:**
```yaml
build-vue:
  uses: ./.github/workflows/action-build.yml
  with:
    node-version: '18'
    build-command: 'npm run build'
    artifact-name: 'vue-app-build'
    artifact-path: './dist'
```

3. **Proyecto con configuración personalizada:**
```yaml
build-custom:
  uses: ./.github/workflows/action-build.yml
  with:
    node-version: '20'
    build-command: 'npm run build:production'
    artifact-name: 'production-build'
    artifact-path: './build'
    retention-days: 30
```

### Acción de SonarQube

La acción de SonarQube está diseñada para análisis de calidad de código:

#### Casos de uso comunes:

1. **Análisis básico:**
```yaml
sonar-basic:
  uses: ./.github/workflows/action-sonar.yml
  with:
    node-version: '18'
    project-key: 'my-project'
    project-name: 'My Project'
    sonar-host-url: 'https://sonar.example.com'
  secrets:
    SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

2. **Análisis con configuración personalizada:**
```yaml
sonar-custom:
  uses: ./.github/workflows/action-sonar.yml
  with:
    node-version: '18'
    java-version: '17'
    project-key: 'my-project'
    project-name: 'My Project'
    sonar-host-url: 'https://sonar.example.com'
    sources-path: './src'
    exclusions: '**/*.test.js,**/*.spec.js'
    coverage-exclusions: '**/*.test.js,**/*.spec.js,**/node_modules/**,**/coverage/**'
  secrets:
    SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

3. **Análisis para diferentes frameworks:**
```yaml
sonar-react:
  uses: ./.github/workflows/action-sonar.yml
  with:
    node-version: '18'
    project-key: 'react-app'
    project-name: 'React Application'
    sonar-host-url: 'https://sonar.example.com'
    coverage-artifact-name: 'coverage-reports'
    coverage-path: 'coverage/'
  secrets:
    SONAR_TOKEN: ${{ secrets.SONAR_TOKEN }}
```

## Características

### Acción de Build:
- ✅ Configuración automática de Node.js
- ✅ Cache de dependencias npm
- ✅ Instalación automática de dependencias
- ✅ Ejecución de build con manejo de errores
- ✅ Subida de artefactos configurable
- ✅ Resumen de resultados en GitHub
- ✅ Parámetros personalizables

### Acción de SonarQube:
- ✅ Configuración automática de Node.js y Java
- ✅ Descarga automática de reportes de cobertura
- ✅ Instalación de dependencias
- ✅ Análisis de calidad con SonarQube
- ✅ Configuración flexible de exclusiones
- ✅ Resumen de resultados en GitHub
- ✅ Parámetros personalizables para diferentes proyectos

## Notas importantes

### Build Action:
- La acción continúa ejecutándose incluso si el build falla (`continue-on-error: true`)
- Los artefactos se suben independientemente del resultado del build
- Se genera un resumen de resultados en la pestaña de Actions de GitHub

### SonarQube Action:
- Requiere que los reportes de cobertura estén disponibles como artefactos
- Necesita configuración de variables de entorno para SonarQube
- El análisis se ejecuta después de que los tests generen cobertura 