<!-- ONYX_METADATA={"link": "https://github.com/HOP-RAG/HOP/blob/main/backend/onyx/connectors/README.md"} -->

# Como crear un conector nuevo para ACTIVA

Este README explica como contribuir un conector nuevo para ACTIVA dentro del repositorio HOP. Incluye una vista general del diseno, las interfaces y los cambios obligatorios.

Gracias por contribuir.

## Resumen de conectores

Los conectores siguen 3 flujos principales:

- **Load Connector**
  - Indexa documentos en bloque para reflejar un punto en el tiempo.
  - Normalmente obtiene todos los documentos por API o los carga desde algun dump.

- **Poll Connector**
  - Actualiza documentos incrementalmente segun un rango de tiempo.
  - El job en background lo usa para traer cambios nuevos desde la ultima ejecucion.
  - Sirve para mantener el indice actualizado sin volver a fetch / embed / index de todo el conjunto.

- **Slim Connector**
  - Es una version mas liviana para verificar si los documentos siguen existiendo.
  - Debe comportarse igual que un Poll o Load Connector, pero trayendo solo IDs y no el contenido completo.
  - Se usa durante el pruning para eliminar documentos viejos del indice.
  - Las fechas opcionales de inicio y fin pueden ignorarse.

- **Event Based Connectors**
  - Escuchan eventos y actualizan documentos a partir de esos eventos.
  - Hoy no los usa el job en background; existen para futuras extensiones de diseno.

## Implementacion del conector

Revisa [interfaces.py](https://github.com/HOP-RAG/HOP/blob/main/backend/onyx/connectors/interfaces.py) y toma como referencia conectores ya existentes en este repositorio.

Todo conector nuevo debe agregar tests en `backend/tests/daily/connectors`.

### Implementar el conector

El conector debe heredar de una o mas de estas clases:

- `LoadConnector`
- `PollConnector`
- `CheckpointedConnector`
- `CheckpointedConnectorWithPermSync`

El `__init__` debe recibir la configuracion necesaria para decidir que documentos leer y de donde leerlos. Por ejemplo:

- equipo
- topic
- carpeta
- dominio base

Si toda la informacion de acceso vive en la credencial o token, tal vez no haga falta pedir argumentos extra.

`load_credentials` debe recibir un diccionario con toda la informacion de acceso que el conector necesite.

Por ejemplo:

- usuario
- token de acceso

Revisa conectores existentes para ejemplos de `load_from_state` y `poll_source`.

### Tip de desarrollo

Puede ser util probar tu conector por separado mientras lo construyes.
Puedes usar una plantilla como esta:

```commandline
if __name__ == "__main__":
    import time
    test_connector = NewConnector(space="engineering")
    test_connector.load_credentials({
        "user_id": "foobar",
        "access_token": "fake_token"
    })
    all_docs = test_connector.load_from_state()

    current = time.time()
    one_day_ago = current - 24 * 60 * 60  # 1 day
    latest_docs = test_connector.poll_source(one_day_ago, current)
```

> Nota: asegúrate de configurar `PYTHONPATH` apuntando a `onyx/backend` antes de correr este ejemplo.

## Cambios adicionales obligatorios

### Cambios de backend

- Agrega un tipo nuevo en [DocumentSource](https://github.com/HOP-RAG/HOP/blob/main/backend/onyx/configs/constants.py).
- Agrega el mapeo de `DocumentSource` al conector correcto [aqui](https://github.com/HOP-RAG/HOP/blob/main/backend/onyx/connectors/factory.py#L33).

### Cambios de frontend

- Agrega la definicion del conector en `SOURCE_METADATA_MAP` [aqui](https://github.com/HOP-RAG/HOP/blob/main/web/src/lib/sources.ts#L59).
- Agrega la definicion del formulario en `connectorConfigs` [aqui](https://github.com/HOP-RAG/HOP/blob/main/web/src/lib/connectors/connectors.tsx#L79).

### Cambios de documentacion

Crea la pagina de documentacion del conector, incluyendo imagenes guia y pasos para obtener credenciales y configurarlo en ACTIVA.

Despues actualiza la fuente de documentacion que alimenta `docs.activa.ai`.

## Antes de abrir el PR

1. Prueba el flujo completo de punta a punta, incluyendo la creacion del conector y la indexacion de documentos nuevos.
2. Adjunta un video mostrando la creacion exitosa desde la UI, empezando en `Add Connector`.
3. Agrega una carpeta con tests en `backend/tests/daily/connectors`. Como referencia puedes revisar el [test de Confluence](https://github.com/HOP-RAG/HOP/blob/main/backend/tests/daily/connectors/confluence/test_confluence_basic.py).
4. En la descripcion del PR, incluye una guia para levantar el origen necesario y hacer pasar esos tests.
5. Corre formato y lint antes de pedir review. Puedes apoyarte en [CONTRIBUTING.md](https://github.com/HOP-RAG/HOP/blob/main/CONTRIBUTING.md#contribuir-con-codigo).
