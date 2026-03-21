## Primeros pasos

ACTIVA dentro del repositorio HOP es una aplicacion full-stack y depende de software externo, en particular:

- [Postgres](https://www.postgresql.org/) (base de datos relacional)
- [Vespa](https://vespa.ai/) (base vectorial / motor de busqueda)
- [Redis](https://redis.io/) (cache)
- [MinIO](https://min.io/) (almacenamiento de archivos)
- [Nginx](https://nginx.org/) (normalmente no hace falta para flujos de desarrollo)

> **Nota:**
> Esta guia explica como compilar y ejecutar ACTIVA localmente desde el codigo fuente usando contenedores Docker para los servicios externos anteriores. Consideramos que esta combinacion es la mas comoda para desarrollo. Si prefieres usar imagenes preconstruidas, mas abajo tambien se incluyen instrucciones para levantar todo el stack de ACTIVA dentro de Docker.

### Configuracion local

Asegurate de usar Python 3.11. Si necesitas ayuda para instalarlo en macOS, revisa [contributing_macos.md](./contributing_macos.md).

Si usas una version menor, tendras que ajustar partes del codigo.
Si usas una version mayor, algunas librerias pueden no estar disponibles o fallar (por ejemplo, antes tuvimos problemas con Tensorflow en versiones mas nuevas de Python).

#### Backend: requisitos de Python

Actualmente usamos [uv](https://docs.astral.sh/uv/) y recomendamos crear un [entorno virtual](https://docs.astral.sh/uv/pip/environments/#using-a-virtual-environment).

Por comodidad, aqui tienes un comando para hacerlo:

```bash
uv venv .venv --python 3.11
source .venv/bin/activate
```

_En Windows, activa el entorno virtual con Command Prompt:_

```bash
.venv\Scripts\activate
```

Si usas PowerShell, el comando cambia ligeramente:

```powershell
.venv\Scripts\Activate.ps1
```

Instala las dependencias de Python:

```bash
uv sync --all-extras
```

Instala Playwright para Python (navegador headless requerido por el Web Connector):

```bash
uv run playwright install
```

#### Frontend: dependencias de Node

El frontend de HOP usa Node `v22.20.0`. Recomendamos usar [Node Version Manager (nvm)](https://github.com/nvm-sh/nvm) para administrar versiones de Node. Una vez instalado, puedes ejecutar:

```bash
nvm install 22 && nvm use 22
node -v # verifica la version activa
```

Entra a `web/` y ejecuta:

```bash
npm i
```

## Formato y lint

### Backend

Para el backend debes configurar los hooks de pre-commit (black / reorder-python-imports).

Luego ejecuta:

```bash
uv run pre-commit install
```

Tambien usamos `mypy` para chequeo estatico de tipos.
El codebase esta completamente tipado y queremos mantenerlo asi.
Para correr `mypy` manualmente, ejecuta `uv run mypy .` desde el directorio `backend/`.

### Web

Usamos `prettier` para formateo. La version correcta se instala con `npm i` dentro de `web/`.
Para correr el formatter, usa `npx prettier --write .` desde `web/`.

Pre-commit tambien ejecuta prettier automaticamente sobre los archivos que tocaste. Si reformatea algo, tu commit va a fallar.
Solo vuelve a stagear los cambios y haz commit otra vez.

# Ejecutar la aplicacion para desarrollo

## Desarrollo con el depurador de VS Code (recomendado)

**Recomendamos fuertemente usar el depurador de VS Code para desarrollar.**
Consulta [contributing_vscode.md](./contributing_vscode.md) para mas detalles.

Si prefieres, tambien puedes seguir las instrucciones manuales de abajo.

## Ejecucion manual para desarrollo
### Contenedores Docker para software externo

Necesitas tener Docker instalado para levantar estos contenedores.

Primero ve a `deployment/docker_compose` y despues inicia Postgres/Vespa/Redis/MinIO con:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d index relational_db cache minio
```

(`index` corresponde a Vespa, `relational_db` a Postgres y `cache` a Redis)

### Ejecutar ACTIVA localmente

Para iniciar el frontend, entra a `web/` y ejecuta:

```bash
npm run dev
```

Luego inicia el model server, que corre los modelos NLP locales.
Entra a `backend/` y ejecuta:

```bash
uvicorn model_server.main:app --reload --port 9000
```

_En Windows (compatible con PowerShell y Command Prompt):_

```bash
powershell -Command "uvicorn model_server.main:app --reload --port 9000"
```

La primera vez que ejecutes ACTIVA, tendras que correr las migraciones de Postgres.
Despues de eso ya no hace falta, salvo que cambien los modelos de base de datos.

Entra a `backend/` y con el venv activo ejecuta:

```bash
alembic upgrade head
```

Despues inicia la cola de tareas que orquesta los jobs en background.
Los jobs mas pesados se ejecutan de forma asincrona fuera del API server.

Todavia en `backend/`, ejecuta:

```bash
python ./scripts/dev_run_background_jobs.py
```

Para correr el backend API server, vuelve a `backend/` y ejecuta:

```bash
AUTH_TYPE=basic uvicorn onyx.main:app --reload --port 8080
```

_En Windows (compatible con PowerShell y Command Prompt):_

```bash
powershell -Command "
    $env:AUTH_TYPE='basic'
    uvicorn onyx.main:app --reload --port 8080
"
```

> **Nota:**
> Si necesitas mas detalle en logs, agrega la variable de entorno `LOG_LEVEL=DEBUG` al servicio correspondiente.

#### Cierre

En este punto deberias tener 4 procesos corriendo:

- Web server
- Backend API
- Model server
- Background jobs

Ahora visita `http://localhost:3000` en tu navegador. Deberias ver el asistente inicial de ACTIVA para conectar tu proveedor externo de LLM a la plataforma.

Ya tienes una instancia local de ACTIVA funcionando.

#### Ejecutar ACTIVA dentro de contenedores

Tambien puedes correr todo el stack de ACTIVA usando imagenes preconstruidas, incluyendo dependencias externas.

Ve a `deployment/docker_compose` y ejecuta:

```bash
docker compose up -d
```

Cuando Docker termine de descargar e iniciar los contenedores, abre `http://localhost:3000` para usar ACTIVA.

Si quieres hacer cambios en ACTIVA y ejecutarlos dentro de Docker, tambien puedes construir una version local de las imagenes con tus modificaciones:

```bash
docker compose up -d --build
```
