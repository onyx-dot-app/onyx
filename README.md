# Hop

Fork local de Onyx renombrado para uso en Windows/Docker con arranque simplificado.

## Qué se ajustó

- `docker compose` con nombre de proyecto `hop`.
- Corrección en `backend/Dockerfile` para scripts `.sh` con `CRLF` (Windows) que en Linux daban error de "archivo no encontrado".
- Valores por defecto de `FILE_STORE_BACKEND` en Docker Compose a `postgres` para evitar que el backend falle si MinIO no está levantado.
- Script `hop.ps1` para levantar/parar todo desde PowerShell sin pelearse con rutas ni perfiles.

## Requisitos

- Docker Desktop (o Docker Engine + Compose)
- PowerShell 5.1+ o PowerShell 7+

## Uso rápido (Windows)

### 1. Levantar Hop (modo simple, sin MinIO)

```powershell
.\hop.ps1
```

Esto usa almacenamiento de archivos en PostgreSQL (`FILE_STORE_BACKEND=postgres`) para evitar errores de S3/MinIO.

### 2. Levantar Hop con MinIO / S3

```powershell
.\hop.ps1 -ConS3
```

Esto activa el profile `s3-filestore` y configura `FILE_STORE_BACKEND=s3`.

### 3. Ver logs

```powershell
.\hop.ps1 -Accion logs
```

### 4. Ver estado

```powershell
.\hop.ps1 -Accion ps
```

### 5. Bajar contenedores

```powershell
.\hop.ps1 -Accion down
```

### 6. Rebuild limpio (si cambiaste Dockerfile)

```powershell
.\hop.ps1 -Accion build
.\hop.ps1 -Accion up -SinBuild
```

## Notas importantes

- El código interno sigue usando nombres técnicos como `onyx` en paquetes Python, imágenes Docker y rutas internas para no romper imports ni builds.
- El cambio a `Hop` se aplicó en branding operativo/documentación local y nombre del proyecto de Docker Compose.
- Si ya tenés una `.env` personalizada en `deployment/docker_compose`, el script sigue funcionando, pero fuerza el modo de almacenamiento según uses o no `-ConS3`.

## Error típico resuelto: `setup_craft_templates.sh` "no encontrado"

En Windows, varios scripts se guardan con saltos de línea `CRLF`. Dentro del contenedor Linux eso puede verse como un "archivo no encontrado" aunque el archivo exista.

Se corrigió en `backend/Dockerfile` convirtiendo los scripts a formato Unix (`LF`) durante el build.

## URLs por defecto

- App (nginx): `http://localhost:3000`
- App (también expuesta): `http://localhost:80`
- API directa (con `docker-compose.dev.yml`): `http://localhost:8080`

