# Backend de HOP

Este directorio contiene los servicios backend que impulsan ACTIVA dentro del repositorio HOP.

## Resumen

El backend incluye:

- `backend/onyx/` - Aplicacion principal en FastAPI, conectores, jobs en background, evals y servidor MCP
- `backend/ee/onyx/` - Extensiones Enterprise
- `backend/alembic/` - Migraciones de base de datos
- `backend/tests/` - Tests automatizados

## Nota importante

La marca del repositorio y del producto ya cambio a HOP / ACTIVA, pero muchos paquetes Python, rutas de modulos y variables de entorno siguen usando `onyx` por compatibilidad con el codebase de origen y con las herramientas existentes.

## Comandos comunes de desarrollo

Desde la raiz del repositorio:

```bash
source .venv/bin/activate
uv sync --all-extras
cd backend
alembic upgrade head
uvicorn model_server.main:app --reload --port 9000
AUTH_TYPE=basic uvicorn onyx.main:app --reload --port 8080
python ./scripts/dev_run_background_jobs.py
```

## Documentacion relacionada

- [Desarrollo de conectores](./onyx/connectors/README.md)
- [Jobs en background](./onyx/background/README.md)
- [Servidor MCP](./onyx/mcp_server/README.md)
- [Evaluaciones](./onyx/evals/README.md)
- [Configuracion para contribuyentes](../contributing_guides/dev_setup.md)
