# **Jira Service Management Connector**  
**Objetivo:** Crear un conector que extraiga **todos los tickets** (issues) de un proyecto especificado en **Jira Service Management (JSM)** y los entregue a la plataforma de integración de @mau16ro siguiendo el estándar de “connectors” descrito en el README del proyecto.

---  

## 1. Visión General y Alcance  

| **Funcionalidad** | **Descripción** |
|-------------------|-----------------|
| **Extracción completa** | Obtener **todos** los tickets (incidencias) de un proyecto JSM determinado. |
| **Sincronización incremental** | Detectar cambios (nuevos, actualizados, cerrados) mediante `updated >= <last_sync>` y evitar re‑descargas masivas. |
| **Manejo de paginación** | Recorrer todas las páginas del API (máx. 1000 resultados por request). |
| **Rate‑limit & Retries** | Respetar los límites de Atlassian, reintentar con back‑off exponencial. |
| **Transformación** | Mapear campos de JSM a un **esquema normalizado** (ID, summary, description, status, priority, requester, created, updated, etc.). |
| **Entrega** | Publicar los tickets a la capa de ingestión de la plataforma (ej. RabbitMQ, Kafka, HTTP POST, etc.). |
| **Configuración** | Parámetros vía variables de entorno o archivo YAML (URL, proyecto, credenciales, batch size, etc.). |
| **Observabilidad** | Logs estructurados, métricas (tickets leídos, tiempo de ejecución, errores). |
| **Despliegue** | Imagen Docker, helm chart opcional, CI/CD con GitHub Actions. |

---  

## 2. Prerrequisitos  

| **Elemento** | **Versión mínima** |
|--------------|-------------------|
| Python | 3.10 |
| `requests` o `httpx` (asíncrono) | 0.23+ |
| Docker | 20.10+ |
| Atlassian Cloud / Server | Cuenta con **API Token** y permisos de *Read* en el proyecto JSM. |
| Plataforma de ingestión | (ej. RabbitMQ, Kafka, HTTP endpoint) configurada y accesible. |
| Repositorio Git | Con la estructura de conectores existente. |

> **Nota**: Si la organización usa *Jira Server* (on‑prem), cambiar la URL base a `https://<host>/rest/api/2/` y usar *Basic Auth* con usuario + password o PAT.

---  

## 3. Arquitectura del Conector  

```mermaid
flowchart TD
    subgraph "Conector JSM"
        A[Config Loader] --> B[Auth Provider]
        B --> C[HTTP Client (httpx)]
        C --> D[Paginator]
        D --> E[Transformer]
        E --> F[Publisher (RabbitMQ/HTTP)]
        D --> G[State Store (last_sync.json)]
        G --> D
    end
    subgraph "Plataforma"
        F --> H[Ingestor Central]
    end
```

* **Config Loader** – lee `config.yml` / variables de entorno.  
* **Auth Provider** – genera cabecera `Authorization: Bearer <token>` (API token).  
* **HTTP Client** – wrapper con *retry* y *rate‑limit* handling.  
* **Paginator** – itera sobre `/rest/api/3/search` con `startAt` / `maxResults`.  
* **Transformer** – convierte la respuesta JSON de JSM a nuestro esquema interno.  
* **Publisher** – envía cada ticket al bus de mensajes o endpoint HTTP.  
* **State Store** – persiste `last_sync` (timestamp ISO) para sincronizaciones incrementales.

---  

## 4. Detalles de Implementación  

### 4.1. Estructura de Directorios  

```
jira-sm-connector/
├── src/
│   ├── __init__.py
│   ├── main.py                # entrypoint
│   ├── config.py              # carga de configuración
│   ├── auth.py                # generación del header
│   ├── client.py              # httpx wrapper + retry
│   ├── paginator.py           # iterador paginado
│   ├── transformer.py         # JSM → schema
│   ├── publisher.py           # RabbitMQ / HTTP
│   └── state.py               # persistencia last_sync
├── tests/
│   ├── unit/
│   └── integration/
├── Dockerfile
├── helm/
│   └── chart.yaml
├── config.yml
├── requirements.txt
└── README.md
```

### 4.2. Configuración (`config.yml`)  

```yaml
jira:
  base_url: "https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3"
  cloud_id: "YOUR_CLOUD_ID"           # opcional si usas URL completa
  project_key: "SM"
  api_token: "${JIRA_API_TOKEN}"      # inyectado vía env
  email: "${JIRA_USER_EMAIL}"
  page_size: 100                      # máximo 1000 (pero 100 es recomendado)
  jql: ""                             # filtro opcional adicional
  fields:                             # campos que queremos en la respuesta
    - id
    - key
    - summary
    - description
    - status
    - priority
    - reporter
    - created
    - updated
    - assignee
    - customfield_10011   # ejemplo: SLA breach time

output:
  mode: "rabbitmq"                     # o "http"
  rabbitmq:
    url: "amqp://user:pass@rmq:5672/"
    exchange: "jira.tickets"
    routing_key: "sm.project"
  http:
    endpoint: "https://ingest.mycompany.com/tickets"
    auth_token: "${INGEST_TOKEN}"

state:
  file_path: "/data/last_sync.json"
  format: "iso8601"                    # ex: 2024-07-01T12:00:00Z
```

> **Tip**: Mantener los secretos fuera del repo, usar *GitHub Secrets* + *GitHub Actions* o *Kubernetes Secrets*.

### 4.3. Autenticación (`auth.py`)  

```python
import base64
import os

def build_auth_header(email: str, api_token: str) -> dict:
    """
    Atlassian Cloud usa Basic Auth con email:api_token codificado en base64.
    """
    token_bytes = f"{email}:{api_token}".encode("utf-8")
    b64_token = base64.b64encode(token_bytes).decode("utf-8")
    return {"Authorization": f"Basic {b64_token}"}
```

### 4.4. Cliente HTTP con Retry (`client.py`)  

```python
import httpx
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

log = logging.getLogger(__name__)

class JiraClient:
    def __init__(self, base_url: str, headers: dict, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.timeout = timeout
        self.client = httpx.AsyncClient(timeout=self.timeout)

    @retry(
        reraise=True,
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(httpx.HTTPStatusError)
    )
    async def get(self, endpoint: str, params: dict = None) -> dict:
        url = f"{self.base_url}{endpoint}"
        response = await self.client.get(url, headers=self.headers, params=params)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Atlassian devuelve 429 para rate‑limit
            if exc.response.status_code == 429:
                retry_after = int(exc.response.headers.get("Retry-After", "5"))
                log.warning("Rate limit hit, sleeping %s seconds", retry_after)
                await asyncio.sleep(retry_after)
                raise
            else:
                log.error("Jira request failed: %s", exc)
                raise
        return response.json()
```

### 4.5. Paginación (`paginator.py`)  

```python
import asyncio
from typing import AsyncGenerator, List, Dict

class IssuePaginator:
    def __init__(self, client: JiraClient, project_key: str,
                 jql: str = "", fields: List[str] = None,
                 page_size: int = 100):
        self.client = client
        self.project_key = project_key
        self.jql = jql
        self.fields = fields or []
        self.page_size = page_size

    async def _build_params(self, start_at: int) -> dict:
        query = f'project = {self.project_key}'
        if self.jql:
            query = f'({query}) AND ({self.jql})'

        return {
            "jql": query,
            "startAt": start_at,
            "maxResults": self.page_size,
            "fields": ",".join(self.fields),
        }

    async def iterate_issues(self) -> AsyncGenerator[Dict, None]:
        start = 0
        total = None

        while total is None or start < total:
            params = await self._build_params(start)
            data = await self.client.get("/search", params=params)
            issues = data.get("issues", [])
            total = data.get("total", 0)

            if not issues:
                break

            for issue in issues:
                yield issue

            start += len(issues)
```

### 4.6. Transformación (`transformer.py`)  

```python
from datetime import datetime
from typing import Dict

def iso_to_utc(ts: str) -> str:
    # Jira siempre devuelve ISO 8601 en UTC
    return datetime.fromisoformat(ts.rstrip('Z')).isoformat() + "Z"

def transform_issue(raw: Dict) -> Dict:
    fields = raw["fields"]
    return {
        "id": raw["id"],
        "key": raw["key"],
        "summary": fields.get("summary"),
        "description": fields.get("description"),
        "status": fields.get("status", {}).get("name"),
        "priority": fields.get("priority", {}).get("name"),
        "requester": fields.get("reporter", {}).get("emailAddress"),
        "assignee": fields.get("assignee", {}).get("emailAddress"),
        "created": iso_to_utc(fields.get("created")),
        "updated": iso_to_utc(fields.get("updated")),
        # Ejemplo de campo custom (SLA)
        "sla_breach": fields.get("customfield_10011"),
    }
```

### 4.7. Publicación (`publisher.py`)  

#### 4.7.1. RabbitMQ  

```python
import json
import pika
import logging

log = logging.getLogger(__name__)

class RabbitPublisher:
    def __init__(self, url: str, exchange: str, routing_key: str):
        params = pika.URLParameters(url)
        self.conn = pika.BlockingConnection(params)
        self.channel = self.conn.channel()
        self.exchange = exchange
        self.routing_key = routing_key

    def publish(self, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.channel.basic_publish(
            exchange=self.exchange,
            routing_key=self.routing_key,
            body=body,
            properties=pika.BasicProperties(
                delivery_mode=2  # persistent
            )
        )
        log.debug("Ticket %s publicado en %s", payload["key"], self.routing_key)

    def close(self):
        self.conn.close()
```

#### 4.7.2. HTTP  

```python
import httpx
import json
import logging

log = logging.getLogger(__name__)

class HttpPublisher:
    def __init__(self, endpoint: str, auth_token: str = None):
        self.endpoint = endpoint
        self.headers = {"Content-Type": "application/json"}
        if auth_token:
            self.headers["Authorization"] = f"Bearer {auth_token}"
        self.client = httpx.AsyncClient()

    async def publish(self, payload: dict):
        resp = await self.client.post(
            self.endpoint,
            json=payload,
            headers=self.headers,
            timeout=10,
        )
        resp.raise_for_status()
        log.debug("Ticket %s enviado a %s", payload["key"], self.endpoint)

    async def close(self):
        await self.client.aclose()
```

### 4.8. Estado Persistido (`state.py`)  

```python
import