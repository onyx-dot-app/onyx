# Onyx Developer Script

[![Deploy Status](https://github.com/onyx-dot-app/onyx/actions/workflows/release-devtools.yml/badge.svg)](https://github.com/onyx-dot-app/onyx/actions/workflows/release-devtools.yml)
[![PyPI](https://img.shields.io/pypi/v/onyx-devtools.svg)](https://pypi.org/project/onyx-devtools/)

`ods` is [onyx.app](https://github.com/onyx-dot-app/onyx)'s devtools utility script.
It is packaged as a python [wheel](https://packaging.python.org/en/latest/discussions/package-formats/) and available from [PyPI](https://pypi.org/project/onyx-devtools/).

## Installation

A stable version of `ods` is provided in the default [python venv](https://github.com/onyx-dot-app/onyx/blob/main/CONTRIBUTING.md#backend-python-requirements)
which is synced automatically if you have [pre-commit](https://github.com/onyx-dot-app/onyx/blob/main/CONTRIBUTING.md#formatting-and-linting)
hooks installed.

While inside the Onyx repository, activate the root project's venv,

```shell
source .venv/bin/activate
```

If you prefer to use the latest version of `ods` and _not_ the stable version in the `pyproject.toml`,

```shell
uvx --from onyx-devtools ods
```

### Autocomplete

`ods` provides autocomplete for `bash`, `fish`, `powershell` and `zsh` shells.

For more information, see `ods completion <shell> --help` for your respective `<shell>`.

#### zsh

*Linux*

```shell
ods completion zsh | sudo tee "${fpath[1]}/_ods" > /dev/null
```

*macOS*

```shell
ods completion zsh > $(brew --prefix)/share/zsh/site-functions/_ods
```

#### bash

```shell
ods completion bash | sudo tee /etc/bash_completion.d/ods > /dev/null
```

_Note: bash completion requires the [bash-completion](https://github.com/scop/bash-completion/) package be installed._

## Upgrading

To upgrade the stable version in the `pyproject.toml`,

```shell
uv add --dev onyx-devtools --upgrade-package onyx-devtools
```

## Building from source

Generally, `go build .` or `go install .` are sufficient.

To build the wheel,

```shell
uv build --wheel
```

To build and install the wheel,

```shell
uv pip install .
```

## Deploy

Releases are deployed automatically when git tags prefaced with `ods/` are pushed to [GitHub](https://github.com/onyx-dot-app/onyx/tags).

The [release-tag](https://pypi.org/project/release-tag/) package can be used to calculate and push the next tag automatically,

```shell
tag --prefix ods
```

See also, [`.github/workflows/release-devtools.yml`](https://github.com/onyx-dot-app/onyx/blob/main/.github/workflows/release-devtools.yml).
