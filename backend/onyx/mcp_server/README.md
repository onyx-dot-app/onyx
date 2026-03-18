# Servidor MCP de ACTIVA

## Resumen

El servidor MCP de ACTIVA permite que LLMs se conecten a tu instancia de ACTIVA y accedan a su base de conocimiento y capacidades de busqueda mediante [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

Con este servidor puedes:

- buscar en la base de conocimiento indexada
- habilitar web search para tus LLMs
- subir y administrar documentos en ACTIVA

Todos los controles de acceso se administran desde la aplicacion principal de ACTIVA.

## Autenticacion

Debes enviar un Personal Access Token o API Key de ACTIVA en el header `Authorization` como Bearer token.

El servidor valida y reenvia ese token en cada request.

Dependiendo del uso, en el futuro puede soportar OAuth y `stdio`.

## Configuracion por defecto

- **Transporte:** HTTP POST (MCP sobre HTTP)
- **Puerto:** 8090
- **Framework:** FastMCP con wrapper FastAPI
- **Base de datos:** ninguna; todo delega al API server

## Arquitectura

El servidor MCP esta construido sobre [FastMCP](https://github.com/jlowin/fastmcp) y corre junto al API server principal:

```text
LLM Client
  -> MCP Server (8090)
      -> API Server (8080)
```

## Configurar clientes MCP

### Claude Desktop

Agrega esto a tu configuracion de Claude Desktop (`~/Library/Application Support/Claude/claude_desktop_config.json` en macOS):

```json
{
  "mcpServers": {
    "activa": {
      "url": "https://[YOUR_ACTIVA_DOMAIN]:8090/",
      "transport": "http",
      "headers": {
        "Authorization": "Bearer YOUR_ACTIVA_TOKEN_HERE"
      }
    }
  }
}
```

### Otros clientes MCP

La mayoria de clientes MCP soportan transporte HTTP con headers personalizados. Revisa la documentacion de tu cliente.

## Capacidades

### Tools

1. `search_indexed_documents`
   Busca dentro de la base de conocimiento privada indexada en ACTIVA y devuelve documentos rankeados con snippets, score y metadata.

2. `search_web`
   Busca en Internet informacion publica y resultados recientes.

3. `open_urls`
   Recupera el contenido completo de URLs especificas, util para profundizar despues de `search_web`.

### Resources

1. `indexed_sources`
   Lista las fuentes documentales indexadas en el tenant, por ejemplo `"confluence"` o `"github"`.

## Desarrollo local

### Levantar el servidor MCP

El servidor MCP se levanta automaticamente con la tarea `Run All Onyx Services` definida en `launch.json`. Ese sigue siendo el nombre tecnico actual del perfil.

Tambien puedes ejecutarlo de manera independiente desde el depurador de VS Code.

### Probar con MCP Inspector

[MCP Inspector](https://github.com/modelcontextprotocol/inspector) sirve para depurar servidores MCP:

```bash
npx @modelcontextprotocol/inspector http://localhost:8090/
```

**Configuracion en Inspector:**

1. Ignora las opciones de OAuth
2. Abre la pestana **Authentication**
3. Selecciona **Bearer Token**
4. Pega tu token Bearer de ACTIVA
5. Haz clic en **Connect**

Una vez conectado puedes:

- explorar tools disponibles
- probar llamadas con distintos parametros
- inspeccionar payloads request / response
- depurar problemas de autenticacion

### Health check

Verifica que el servidor este corriendo:

```bash
curl http://localhost:8090/health
```

Deberias recibir:

```json
{
  "status": "healthy"
}
```

## Variables de entorno

### Configuracion del servidor MCP

- `MCP_SERVER_PORT`: puerto HTTP del servidor MCP. Por defecto `8090`.
- `MCP_SERVER_HOST`: host donde escucha el servidor MCP. Por defecto `0.0.0.0`.

### Conexion con el API server

- `MCP_API_KEY_HEADER`: header usado para reenviar el token Bearer.
- `API_SERVER_URL_OVERRIDE_FOR_HTTP_REQUESTS`: URL override opcional. Si esta presente, tiene prioridad sobre protocolo y host. Es util para self-hosting del servidor MCP contra un backend hospedado de ACTIVA.
