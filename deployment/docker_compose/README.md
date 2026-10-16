# Deployment Guide

Follow these steps to deploy the application stack using Docker Compose.

---

## 1. Clone the Repository

Clone the repository to your server and enter the project root directory:

```bash
git clone <repository-url>
cd <repository-name>

```

---

## 2. Prepare Data Directory and Bind Mount Permissions

Create the local data directory and update its permissions so the Docker containers can read and write to the mounted volumes without ownership conflicts:

```bash
mkdir -p data
sudo chown -R 1000:1000 data

```

> **Note:** Adjust `1000:1000` if your containers run under a different target UID/GID.

---

## 3. Configure Environment Variables

Navigate to the deployment directory, copy the template environment file, and edit it with your configuration values:

```bash
cd deployment/docker_compose
cp env.template .env
nano .env

```

> **Note:** Fill in all required database credentials, API keys, host domains, and secrets inside `.env` before proceeding.

---

## 4. Launch the Services

Start the Docker Compose services in detached mode:

```bash
docker compose up -d

```

To verify that all containers are running successfully:

```bash
docker compose ps
docker compose logs -f

```