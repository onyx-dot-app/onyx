<!-- ONYX_METADATA={"link": "https://github.com/HOP-RAG/HOP/blob/main/web/README.md"} -->

Este es el frontend de ACTIVA dentro del repositorio HOP. Esta construido con [Next.js](https://nextjs.org/) y fue inicializado con [`create-next-app`](https://github.com/vercel/next.js/tree/canary/packages/create-next-app).

## Primeros pasos

Instala Node / npm: https://docs.npmjs.com/downloading-and-installing-node-js-and-npm

Instala todas las dependencias:

```bash
npm i
```

Luego levanta el servidor de desarrollo:

```bash
npm run dev
```

Abre [http://localhost:3000](http://localhost:3000) en tu navegador para ver el resultado.

_Nota:_ si tienes problemas para acceder a esa URL, prueba configurando la variable de entorno `WEB_DOMAIN` con `http://127.0.0.1:3000` y entra por esa direccion.

> [!TIP]
> Si tienes [pre-commit](https://github.com/HOP-RAG/HOP/blob/main/CONTRIBUTING.md#contribuir-con-codigo) configurado, los paquetes se instalan automaticamente al cambiar de rama cuando `package.json` se modifica.

### Conectarse a un backend hospedado de ACTIVA

Si quieres probar tu servidor frontend local contra un backend hospedado (por ejemplo, staging o produccion), crea un archivo `.env.local` dentro de `web/` con esta configuracion:

```text
# Apunta el servidor local al backend hospedado
INTERNAL_URL=https://staging.activa.example/api

# Origen publico del backend para flujos de WebSocket que corren en el navegador.
# El nombre de esta variable sigue siendo `NEXT_PUBLIC_ONYX_BACKEND_URL`
# por compatibilidad con el codigo actual.
NEXT_PUBLIC_ONYX_BACKEND_URL=https://staging.activa.example

# Cookie de depuracion para autenticar contra un backend remoto
# Esta cookie se inyecta automaticamente en requests API cuando estas en modo desarrollo
# Para obtenerla:
#   1. Entra al backend objetivo de ACTIVA e inicia sesion
#   2. Abre DevTools (F12) -> Application -> Cookies -> [tu dominio]
#   3. Busca la cookie "fastapiusersauth" y copia su valor
#   4. Pegalo abajo (sin comillas)
# Nota: esta cookie puede expirar, asi que tal vez tengas que renovarla periodicamente
DEBUG_AUTH_COOKIE=your_cookie_value_here
```

Por defecto esto _NO_ sobreescribe las cookies existentes. Si ya iniciaste sesion antes, tal vez tengas que borrar las cookies del dominio `localhost`.

**Notas importantes:**

- El archivo `.env.local` debe crearse dentro de `web/` al mismo nivel que `package.json`.
- Despues de crear o modificar `.env.local`, reinicia el servidor de desarrollo para que los cambios tengan efecto.
- Configura `NEXT_PUBLIC_ONYX_BACKEND_URL` cuando el trafico WebSocket del navegador deba ir a un dominio remoto HTTPS en lugar de `localhost`.
- `DEBUG_AUTH_COOKIE` solo se usa en modo desarrollo (`NODE_ENV=development`).
- Si `INTERNAL_URL` no esta definida, el frontend se conectara al backend local en `http://127.0.0.1:8080`.
- Mantén tu archivo `.env.local` seguro y nunca lo subas al control de versiones.

## Testing

Este proceso de testing puede resetear la aplicacion a un estado limpio.
No lo ejecutes si no quieres hacerlo.

Levanta toda la aplicacion y luego:

1. Instala las dependencias de Playwright

```bash
npx playwright install
```

2. Ejecuta Playwright

```bash
npx playwright test
```

Para correr un solo test:

```bash
npx playwright test landing-page.spec.ts
```

Si estas corriendo localmente, las opciones interactivas pueden ayudarte a ver exactamente lo que esta pasando:

```bash
npx playwright test --ui
npx playwright test --headed
```

3. Inspecciona los resultados

Por defecto, `playwright.config.ts` deja la salida en:

```bash
web/output/playwright/
```

4. Screenshots para regresion visual

Las screenshots se capturan automaticamente durante los tests y se guardan en `web/output/screenshots/`.
Para comparar screenshots entre corridas de CI usa:

```bash
ods screenshot-diff compare --project admin
```

Para mas informacion, revisa [tools/ods/README.md](https://github.com/HOP-RAG/HOP/blob/main/tools/ods/README.md#screenshot-diff---visual-regression-testing).
