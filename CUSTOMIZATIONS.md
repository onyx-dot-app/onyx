# CUSTOMIZATIONS

Este archivo documenta las diferencias conocidas entre este fork y el codebase upstream de Onyx.

Su objetivo es ayudar a:

- entender la identidad del fork HOP / ACTIVA;
- localizar cambios que pueden generar conflictos al traer parches selectivos desde upstream;
- distinguir entre rebranding real, cambios operativos del fork y deuda de compatibilidad que todavia conserva nombres `onyx`.

## Resumen ejecutivo

- **Repositorio / distribucion local**: `HOP`
- **Marca visible del producto**: `ACTIVA`
- **Codebase de origen**: `Onyx`
- **Estrategia general del fork**: rebranding visible hacia ACTIVA, manteniendo muchos identificadores tecnicos `onyx` para no romper imports, tooling, imagenes, charts y rutas internas.

## Punto de sincronizacion con upstream

> Nota: este repositorio no tiene un remote `upstream` configurado. Por eso, el punto de sincronizacion indicado abajo es **inferido** a partir del historial git disponible localmente.

- **Ultimo commit upstream identificable en el historial actual**:
  - Commit: `11cfc92f159458571bd02f35417d2f24b238d27e`
  - Fecha: `2026-03-17 01:04:06 +0000`
  - Mensaje: `chore(hook): DB changes (#9337)`
- **Primer commit explicito de divergencia de marca identificado**:
  - Commit: `0fd9881d2025b3134fb67483751b1918fe66b34d`
  - Fecha: `2026-03-16 20:34:45 -0500`
  - Mensaje: `Renamed to ACTIVA`

## 1. Cambio de marca y rationale

### Decision de naming

- **HOP** es el nombre del repositorio, de la distribucion local y del flujo operativo/documental del fork.
- **ACTIVA** es la marca expuesta al usuario final dentro de la aplicacion.
- **Onyx** se conserva en muchos nombres tecnicos por compatibilidad con el codebase original.

### Rationale

- La marca visible del producto cambia para separar la identidad comercial del fork respecto de Onyx.
- Se evita un rename profundo de paquetes/modulos para no romper imports Python, rutas Next.js, nombres de charts, variables de entorno, pipelines y tooling heredado.
- El resultado es un modelo de convivencia:
  - **marca visible** = ACTIVA;
  - **nombres tecnicos internos** = frecuentemente `onyx`.

### Evidencia en el repositorio

- `backend/onyx/configs/constants.py`: `ONYX_DEFAULT_APPLICATION_NAME = "ACTIVA"`
- `web/src/lib/constants.ts`: `DEFAULT_APPLICATION_NAME = "ACTIVA"`
- `web/src/app/layout.tsx`: metadata, iconos y descripcion publicos de ACTIVA
- `AGENTS.md`, `CONTRIBUTING.md`, `backend/README.md`, `web/README.md`: documentacion ya reescrita para HOP / ACTIVA

## 2. Cambios de rebranding documentados

### 2.1 Marca visible en frontend y metadatos

Cambios observados:

- titulo y metadata de la aplicacion cambiados a `ACTIVA`;
- favicon principal cambiado a `activa.ico`;
- logos y logotipos cargados como assets de ACTIVA;
- textos publicos de la aplicacion y de la documentacion interna movidos hacia la marca ACTIVA.

Archivos representativos:

- `web/src/app/layout.tsx`
- `web/src/lib/constants.ts`
- `web/src/app/Landing.tsx`
- `web/src/components/icons/icons.tsx`
- `web/lib/opal/src/icons/activa-logo.tsx`

### 2.2 Cookies, almacenamiento del navegador y claves de configuracion

Cambios observados:

- cookie de tenant renombrada a `activa_tid`;
- cookie de usuario anonimo renombrada a `activa_anonymous_user`;
- claves de configuracion del KV store renombradas a:
  - `activa_settings`
  - `activa_enterprise_settings`
- claves de `localStorage` visibles en navegador ya migradas a prefijo `activa:` en los puntos trabajados del fork.

Compatibilidad transicional implementada:

- el backend todavia puede leer los nombres legacy `onyx_*` para facilitar la transicion;
- el frontend tambien migra ciertos valores legacy de `localStorage` a claves nuevas con prefijo `activa:`.

Archivos representativos:

- `backend/onyx/configs/constants.py`
- `backend/onyx/server/settings/store.py`
- `backend/ee/onyx/server/enterprise_settings/store.py`
- `backend/ee/onyx/server/middleware/tenant_tracking.py`
- `web/src/lib/constants.ts`
- `web/src/hooks/useShowOnboarding.ts`
- `web/src/sections/sidebar/sidebarUtils.ts`

### 2.3 URLs y referencias publicas

Cambios observados:

- base documental del frontend apuntando a `https://docs.activa.ai`;
- documentacion de contribucion apuntando al repositorio `https://github.com/HOP-RAG/HOP`;
- documentacion de despliegue personalizada para el dominio `klugermax.com`.

Archivos representativos:

- `web/src/lib/constants.ts`
- `CONTRIBUTING.md`
- `contributing_guides/*.md`
- `DEPLOYMENT_GUIDE.md`
- `DEPLOYMENT_QUICKREF.md`
- `START_HERE.md`

## 3. Cambios de paleta de colores

El sistema de color actual del fork vive principalmente en:

- `web/src/app/css/colors.css`
- `web/tailwind-themes/tailwind.config.js`

### Estado actual del sistema visual

- La paleta ya no se limita a un set minimo de neutrales; incorpora familias amplias para UI y marca.
- Se exponen escalas adicionales para composicion visual:
  - `neon-*`
  - `stone-*`
  - `chalk-*`
  - `slate-*`
- Los tokens de tema principal (`theme-primary-*`) siguen anclados sobre `onyx-ink-*` / `onyx-chrome-*`, es decir, el fork conserva alias historicos para compatibilidad aunque la marca visible sea ACTIVA.
- Los highlights tambien usan una familia nueva de acentos neon:
  - `highlight-match`
  - `highlight-selection`
  - `highlight-active`
  - `highlight-accent`

### Lectura practica para futuros merges

- Si upstream toca `colors.css` o `tailwind.config.js`, revisar manualmente:
  - nuevas escalas cromaticas del fork;
  - mapping de `theme-primary-*`;
  - aliases legacy `onyx-*` que todavia sirven de puente para clases existentes.

## 4. Reemplazo de logos y assets

### Assets de marca ACTIVA detectados

- `web/public/activa.ico`
- `web/public/logo.png`
- `web/public/logo-dark.png`
- `web/public/logotype.png`
- `web/public/logotype-dark.png`

### Integracion de los assets

- `web/src/components/icons/icons.tsx` importa los assets como `activaLogo` y `activaLogotype`.
- `web/lib/opal/src/icons/activa-logo.tsx` renderiza el logo ACTIVA desde `/logo.png` y `/logo-dark.png`.
- `web/src/app/layout.tsx` usa `activa.ico` como icono por defecto del sitio.
- El backend conserva la capacidad de servir logo/logotype custom desde runtime o enterprise settings.

### Excepcion importante

El subproyecto `widget/` **todavia conserva branding Onyx** en varios puntos:

- `widget/README.md`: titulo `Onyx Chat Widget`, referencias a `cdn.onyx.app`, `cloud.onyx.app` y footer "Powered by Onyx"
- `widget/src/assets/logo.ts`: logo por defecto descrito como logo de Onyx
- `widget/src/widget.ts`, `widget/src/index.ts`, `widget/src/styles/widget-styles.ts`: comentarios y nombre del componente siguen hablando de Onyx
- `widget/index.html`: demo publica aun muestra `Onyx Chat Widget`

Esto debe considerarse **deuda de rebranding pendiente**, no evidencia de que el fork siga queriendo exponer la marca Onyx al usuario final.

## 5. Cambios de infraestructura

### 5.1 Docker Compose local

Cambios observados:

- el proyecto Compose principal fue renombrado a `hop`;
- los mensajes de arranque del API server ya hablan de `Hop`;
- existe un wrapper PowerShell `hop.ps1` para levantar/parar el stack en Windows.

Archivos representativos:

- `deployment/docker_compose/docker-compose.yml`
- `hop.ps1`

### 5.2 Simplificacion operativa local

Cambios observados:

- arranque local simplificado desde PowerShell;
- por defecto se fuerza `FILE_STORE_BACKEND=postgres` cuando no se activa el perfil S3/MinIO;
- `AUTH_TYPE=disabled` se setea automaticamente en `hop.ps1` para facilitar login local sin configuracion adicional;
- `backend/Dockerfile` normaliza scripts `.sh` a formato Unix (`LF`) para evitar fallos por `CRLF` en entornos Windows.

Archivos representativos:

- `hop.ps1`
- `README.md`
- `backend/Dockerfile`

### 5.3 Dominios y documentacion de despliegue

Cambios observados:

- documentacion de despliegue adaptada al dominio `klugermax.com`;
- instrucciones de descarga/clonado apuntando al repo `HOP-RAG/HOP`;
- documentacion de frontend apuntando a `docs.activa.ai`.

Archivos representativos:

- `DEPLOYMENT_GUIDE.md`
- `DEPLOYMENT_QUICKREF.md`
- `START_HERE.md`
- `web/src/lib/constants.ts`

### 5.4 Docker registries y charts

**Importante**: el fork sigue teniendo deuda de compatibilidad upstream, pero el chart de Helm y las imagenes principales de despliegue ya apuntan a la identidad propia.

Estado actual observado:

- Docker Compose y Helm ya referencian imagenes propias tipo:
  - `hop-rag/activa-backend`
  - `hop-rag/activa-web-server`
  - `hop-rag/activa-model-server`
- Helm usa:
  - chart `name: activa`
  - `home: https://activa.ai/`
  - `sources: https://github.com/HOP-RAG/HOP`

Archivos representativos:

- `deployment/docker_compose/docker-compose.yml`
- `deployment/docker_compose/docker-compose.prod*.yml`
- `deployment/helm/charts/activa/Chart.yaml`
- `deployment/helm/charts/activa/values.yaml`

Interpretacion:

- a nivel operativo local, el fork si diverge;
- a nivel de publicacion de imagenes y charts, todavia existe un fuerte acoplamiento con infraestructura Onyx.

## 6. Features o diferencias funcionales/operativas del fork

### Adiciones claramente identificables

- **Wrapper PowerShell para Windows**:
  - `hop.ps1`
  - simplifica `up/down/logs/ps/build/config`
- **Distribucion local HOP con Compose renombrado**:
  - `deployment/docker_compose/docker-compose.yml` usa `name: hop`
- **Arranque simplificado sin MinIO obligatorio**:
  - default a `FILE_STORE_BACKEND=postgres`
- **Documentacion de despliegue custom para DigitalOcean / dominio propio**:
  - `DEPLOYMENT_GUIDE.md`
  - `DEPLOYMENT_QUICKREF.md`
  - `START_HERE.md`
- **Renombrado de claves visibles en navegador a `activa_*` / `activa:*`**:
  - cookies y `localStorage` de rebranding documentadas arriba

### Remociones o restricciones detectables

- No se identifico en esta revision una eliminacion amplia del feature set de producto respecto de Onyx.
- La divergencia visible del fork parece estar concentrada en:
  - branding;
  - operacion local;
  - documentacion y despliegue;
  - compatibilidad Windows;
  - ajustes de experiencia y almacenamiento visible del navegador.

## 7. Deuda de compatibilidad heredada

Para merges futuros, asumir que estas piezas siguen atadas al naming upstream:

- paquetes Python y rutas de modulo bajo `backend/onyx/` y `backend/ee/onyx/`
- gran parte de variables de entorno y constantes internas con prefijo `ONYX_*`
- muchas rutas de despliegue y artefactos AWS/ECS/Helm
- iconografia y documentacion del subproyecto `widget/`
- algunas URLs legacy o nombres tecnicos como `NEXT_PUBLIC_ONYX_BACKEND_URL`

Esto es deliberado en varios casos y no debe tratarse como error automatico sin evaluar impacto en compatibilidad.

## 8. Recomendaciones para futuros contributors

- Actualiza este archivo cada vez que un cambio del fork:
  - cambie branding visible;
  - agregue una ruta/documentacion de despliegue propia;
  - cambie registries, dominios o charts;
  - renombre cookies, claves de storage o assets visibles al usuario.
- Si se trae un patch desde upstream que toque branding, colores, icons o deployment:
  - revisar manualmente antes de mergear;
  - no asumir que un rename masivo de `onyx` es deseable;
  - priorizar compatibilidad interna salvo que exista un plan de migracion completo.
- Si se completa la migracion del widget o de los registries Docker:
  - documentarlo aqui de inmediato, porque son dos de las areas donde hoy mas conviven artefactos ACTIVA y artefactos Onyx.

## 9. Ultima actualizacion de este documento

- Fecha: `2026-03-18`
- Autor de la actualizacion: Codex
