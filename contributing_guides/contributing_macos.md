## Notas adicionales para usuarios de Mac

Las instrucciones base para preparar el entorno de desarrollo estan en [CONTRIBUTING.md](https://github.com/HOP-RAG/HOP/blob/main/CONTRIBUTING.md).

### Configurar Python

Asegurate primero de tener [Homebrew](https://brew.sh/) instalado.

Despues instala Python 3.11:

```bash
brew install python@3.11
```

Agrega Python 3.11 a tu path incluyendo esta linea en `~/.zshrc`:

```bash
export PATH="$(brew --prefix)/opt/python@3.11/libexec/bin:$PATH"
```

> **Nota:**
> Necesitaras abrir una terminal nueva para que el cambio en el path tenga efecto.

### Configurar Docker

En macOS necesitas instalar [Docker Desktop](https://www.docker.com/products/docker-desktop/) y asegurarte de que este corriendo antes de continuar con los comandos de Docker.

### Formato y lint

En macOS es posible que tengas que quitar algunos atributos de cuarentena para que ciertos hooks se ejecuten correctamente.
Despues de instalar `pre-commit`, corre este comando:

```bash
sudo xattr -r -d com.apple.quarantine ~/.cache/pre-commit
```
