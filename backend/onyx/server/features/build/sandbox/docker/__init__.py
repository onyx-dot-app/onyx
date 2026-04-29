"""Docker-Compose sandbox backend.

Drives the Docker Engine API directly from the api_server to run one
container per user. Mirrors the Kubernetes manager's shape (one pod per
user, sessions as subdirectories) but talks to ``/var/run/docker.sock``
instead of the Kubernetes API.

This module assumes ``SANDBOX_BACKEND=docker``. Importing it is safe even
when the backend isn't selected, but resolving the docker SDK happens
lazily inside the manager so deployments that pin to ``local`` or
``kubernetes`` don't pay for the import.
"""
