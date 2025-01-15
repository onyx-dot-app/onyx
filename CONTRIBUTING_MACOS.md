## Some additional notes for Mac Users

The base instructions to set up the development environment are located in [CONTRIBUTING.md](https://github.com/onyx-dot-app/onyx/blob/main/CONTRIBUTING.md).

### Setting up Python

Ensure [Homebrew](https://brew.sh/) is already set up.

Then install python 3.11.

```bash
brew install python@3.11
```

Add python 3.11 to your path: add the following line to ~/.zshrc

```
export PATH="$(brew --prefix)/opt/python@3.11/libexec/bin:$PATH"
```

> **Note:**
> You will need to open a new terminal for the path change above to take effect.

### Setting up Docker

On macOS, you will need to install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and
ensure it is running before continuing with the docker commands.

### Formatting and Linting

MacOS will likely require you to remove some quarantine attributes on some of the hooks for them to execute properly.
After installing pre-commit, run the following command:

```bash
sudo xattr -r -d com.apple.quarantine ~/.cache/pre-commit
```
