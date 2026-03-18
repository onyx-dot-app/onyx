# Configuracion de depuracion en VS Code

Esta guia explica como configurar y usar las capacidades de depuracion de VS Code con este proyecto.

## Configuracion inicial

1. **Preparar el entorno:**
   - Copia `.vscode/env_template.txt` a `.vscode/.env`
   - Completa las variables de entorno necesarias en `.vscode/.env`

## Usar el depurador

Antes de empezar, asegurate de que Docker Daemon este corriendo.

1. Abre la vista de Debug en VS Code (`Cmd+Shift+D` en macOS)
2. En el selector superior, elige `Clear and Restart External Volumes and Containers` y pulsa el boton verde de play
3. En el selector superior, elige `Run All Onyx Services` y pulsa el boton verde de play. Ese sigue siendo el nombre tecnico actual del perfil aunque la marca del producto ahora sea ACTIVA.
4. Luego abre ACTIVA en tu navegador (por defecto `http://localhost:3000`) y empieza a usar la aplicacion
5. Puedes poner breakpoints haciendo clic a la izquierda de los numeros de linea para depurar mientras la app corre
6. Usa la barra de depuracion para avanzar paso a paso, inspeccionar variables, etc.

Nota: `Clear and Restart External Volumes and Containers` reinicia Postgres y Vespa (`relational-db` e `index`).
Solo ejecutalo si estas de acuerdo con borrar esos datos.

## Funcionalidades

- Hot reload habilitado para el web server y los API servers
- Depuracion de Python configurada con `debugpy`
- Variables de entorno cargadas desde `.vscode/.env`
- Salida de consola organizada en la terminal integrada con pestanas etiquetadas
