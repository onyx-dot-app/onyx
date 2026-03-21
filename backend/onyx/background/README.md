# Resumen de jobs en background de ACTIVA

Los jobs en background que impulsan ACTIVA se encargan de:

1. Hacer pull e indexar documentos desde conectores
2. Actualizar metadata de documentos
3. Limpiar checkpoints y estado de trabajos de indexacion
4. Procesar archivos subidos por usuarios y sus eliminaciones
5. Reportar metricas como longitud de colas para monitoreo

## Mapeo worker -> cola

| Worker | Archivo | Colas |
|--------|---------|-------|
| Primary | `apps/primary.py` | `celery` |
| Light | `apps/light.py` | `vespa_metadata_sync`, `connector_deletion`, `doc_permissions_upsert`, `checkpoint_cleanup`, `index_attempt_cleanup` |
| Heavy | `apps/heavy.py` | `connector_pruning`, `connector_doc_permissions_sync`, `connector_external_group_sync`, `csv_generation`, `sandbox` |
| Docprocessing | `apps/docprocessing.py` | `docprocessing` |
| Docfetching | `apps/docfetching.py` | `connector_doc_fetching` |
| User File Processing | `apps/user_file_processing.py` | `user_file_processing`, `user_file_project_sync`, `user_file_delete` |
| Monitoring | `apps/monitoring.py` | `monitoring` |
| Background (consolidado) | `apps/background.py` | Todas las colas anteriores excepto `celery` |

## Apps que no son workers

| App | Archivo | Proposito |
|-----|---------|-----------|
| **Beat** | `beat.py` | Scheduler de Celery con `DynamicTenantScheduler` para generar tareas periodicas por tenant |
| **Client** | `client.py` | App minima para enviar tareas desde procesos que no son workers, por ejemplo el API server |

### Modulo compartido

`app_base.py` provee:

- `TenantAwareTask` - Clase base que configura el contexto de tenant
- Signal handlers para logging, limpieza y ciclo de vida
- Readiness probes y health checks

## Detalle de workers

### Primary

Es el worker unico que maneja la cola `celery`. Se mantiene como singleton usando el lock de Redis `PRIMARY_WORKER`.

En startup:

- espera a que Redis, Postgres y el indice documental esten sanos
- adquiere el lock singleton
- limpia estados de Redis asociados a jobs de background
- marca como fallidos los index attempts huerfanos

Luego ejecuta tareas programadas por Celery Beat:

| Tarea | Frecuencia | Descripcion |
|------|------------|-------------|
| `check_for_indexing` | 15s | Busca conectores que necesiten indexacion y despacha a `DOCFETCHING` |
| `check_for_vespa_sync_task` | 20s | Encuentra documentos o document sets desactualizados y despacha a `VESPA_METADATA_SYNC` |
| `check_for_pruning` | 20s | Busca conectores que necesiten pruning y despacha a `CONNECTOR_PRUNING` |
| `check_for_connector_deletion` | 20s | Procesa solicitudes de borrado y despacha a `CONNECTOR_DELETION` |
| `check_for_user_file_processing` | 20s | Revisa uploads de usuario y despacha a `USER_FILE_PROCESSING` |
| `check_for_checkpoint_cleanup` | 1h | Limpia checkpoints viejos |
| `check_for_index_attempt_cleanup` | 30m | Limpia index attempts viejos |
| `kombu_message_cleanup_task` | periodica | Limpia mensajes huerfanos de Kombu en DB |
| `celery_beat_heartbeat` | 1m | Heartbeat del watchdog de Beat |

El watchdog corre como un proceso Python separado administrado por `supervisord`.

### Light

Maneja tareas rapidas y poco intensivas. Tiene alta concurrencia.

Ejemplos:

- sincronizacion de permisos y accesos
- sync de document sets, boosts y hidden state
- borrado de documentos marcados para eliminar
- limpieza de checkpoints e index attempts

### Heavy

Maneja tareas largas o pesadas, especialmente pruning y operaciones sandbox. Tiene baja concurrencia.

No interactua directamente con el Document Index; se enfoca en sincronizaciones con sistemas externos y llamadas API de alto volumen.

Tambien genera exports CSV y ejecuta el sandbox para Next.js, Python virtual env, OpenCode AI Agent y archivos de conocimiento.

### Docprocessing, Docfetching y User File Processing

`Docfetching` y `Docprocessing` se encargan de la indexacion documental:

- `Docfetching` ejecuta conectores, trae documentos desde APIs externas, guarda batches en file storage y despacha tareas de procesamiento
- `Docprocessing` recupera esos batches, ejecuta chunking y embeddings, y luego indexa en el Document Index

`User File Processing` se ocupa de archivos subidos directamente por usuarios.

### Monitoring

Recolecta observabilidad y metricas:

- longitudes de colas
- exito y fallo de conectores
- latencias
- memoria de procesos administrados por supervisor
- metricas especificas de cloud y multitenancy
