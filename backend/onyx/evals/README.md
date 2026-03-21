# Evaluaciones de ACTIVA

Este directorio contiene el framework de evaluacion para medir el rendimiento de los sistemas de chat y retrieval de ACTIVA.

## Resumen

El sistema de evaluacion usa [Braintrust](https://www.braintrust.dev/) para ejecutar evaluaciones automatizadas contra datasets de prueba. Sirve para medir la calidad de las respuestas y seguir mejoras a lo largo del tiempo.

## Prerrequisitos

**Importante:** el model server debe estar corriendo para que las evals funcionen correctamente.

## Ejecutar evaluaciones

### Lanzar un job remoto

```bash
HOP/backend$ python -m dotenv -f .vscode/.env run -- python onyx/evals/eval_cli.py --remote --api-key <SUPER_CLOUD_USER_API_KEY> --search-permissions-email <email account to reference> --remote --remote-dataset-name Simple
```

### Ejecutar la CLI localmente

```bash
HOP$ python -m dotenv -f .vscode/.env run -- python backend/onyx/evals/eval_cli.py --local-dataset-path backend/onyx/evals/data/eval.json --search-permissions-email your-user@company.com
```

Guarda `ONYX_EVAL_API_KEY` en tu `.env` para no tener que pasarlo cada vez. El nombre de la variable se mantiene con prefijo `ONYX_` por compatibilidad con el codebase actual.

Tambien necesitas crear una API key desde el panel admin para poder correr evals.

## Desarrollo local

Para desarrollo local, usa `eval_cli.py`. Lo mas comodo suele ser arrancarlo desde la configuracion de VS Code.

### Usar la configuracion de VS Code

1. Abre VS Code en la raiz del proyecto
2. Ve al panel **Run and Debug**
3. Selecciona `Eval CLI`
4. Ejecutalo con el boton play o con `F5`

Eso corre la evaluacion con la configuracion por defecto:

- usa el archivo local `evals/data/data.json`
- habilita salida verbose
- carga variables de entorno y `PYTHONPATH`

### Opciones de CLI

- `--local-data-path`: path al JSON local con datos de prueba
- `--remote-dataset-name`: nombre del dataset remoto en Braintrust
- `--braintrust-project`: nombre del proyecto Braintrust
- `--verbose`: habilita salida verbose
- `--no-send-logs`: no envia logs a Braintrust
- `--local-only`: corre todo localmente sin Braintrust

## Datos de prueba

El sistema usa `evals/data/data.json`. Ese archivo contiene una lista de casos de prueba, cada uno con campos como:

- `input`: pregunta o prompt a evaluar

Ejemplo:

```json
{
  "input": {
    "message": "What is the capital of France?"
  }
}
```

## Configuracion por test

Puedes configurar tools forzadas, assertions y parametros del modelo por caso.

### Configuracion de tools

- `force_tools`: tools a forzar en ese test
- `expected_tools`: tools que deberian ser llamadas
- `require_all_tools`: si es `true`, exige que se llamen todas

### Configuracion del modelo

- `model`: version del modelo
- `model_provider`: proveedor del modelo
- `temperature`: temperatura del modelo

Ejemplo:

```json
[
  {
    "input": {
      "message": "Find information about Python programming"
    },
    "expected_tools": ["SearchTool"],
    "force_tools": ["SearchTool"],
    "model": "gpt-4o"
  },
  {
    "input": {
      "message": "Search the web for recent news about AI"
    },
    "expected_tools": ["WebSearchTool"],
    "model": "claude-3-5-sonnet",
    "model_provider": "anthropic"
  }
]
```

## Evaluaciones multi-turno

Para conversaciones mas realistas, usa un arreglo `messages` en lugar de un solo `message`:

```json
{
  "input": {
    "messages": [
      {
        "message": "What's the latest news about OpenAI today?",
        "expected_tools": ["WebSearchTool", "OpenURLTool"]
      },
      {
        "message": "Now search our internal docs for our OpenAI integration guide",
        "expected_tools": ["SearchTool"]
      },
      {
        "message": "Thanks, that's helpful!",
        "expected_tools": []
      }
    ]
  }
}
```

Cada mensaje puede tener su propia configuracion:

- `message`
- `expected_tools`
- `require_all_tools`
- `force_tools`
- `model`
- `model_provider`
- `temperature`

Las evals multi-turno corren dentro de una sola sesion de chat, asi que el modelo conserva el contexto anterior.

## Tipos de tools disponibles

- `SearchTool`: busqueda interna de documentos
- `WebSearchTool`: busqueda web
- `ImageGenerationTool`: generacion de imagenes
- `PythonTool`: ejecucion de codigo Python
- `OpenURLTool`: abrir y leer URLs

## Dashboard de Braintrust

Despues de correr evaluaciones puedes ver resultados en Braintrust.

Se reportan, entre otras cosas:

- `tool_assertion`: `1.0` si pasa, `0.0` si falla
- metadata como `tools_called`, `tools_called_count` y detalles de assertions
