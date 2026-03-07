# Terminals

> **Alpha** – This project is under active development. APIs and configuration may change.

Multi-tenant terminal orchestrator for [Open Terminal](https://github.com/open-webui/open-terminal). Provisions and manages isolated terminal instances per user with automatic lifecycle management.

## Features

- **Multi-backend** – Docker, Kubernetes, Kubernetes Operator, local process, or static instance
- **Auto-provisioning** – instances created on first request, re-provisioned if missing
- **Idle cleanup** – background manager stops instances after configurable idle timeout
- **Reverse proxy** – catch-all HTTP and WebSocket proxy routes requests to the correct tenant
- **Auth** – Open WebUI JWT validation, static API key, or open access
- **Admin dashboard** – SvelteKit static frontend with tenant management, live health, and config view
- **Audit logging** – structured events via loguru with optional SIEM webhook forwarding
- **Encrypted secrets** – API keys stored encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256)
- **Database migrations** – Alembic migrations run automatically on startup
- **PostgreSQL or SQLite** – async SQLAlchemy supports both via connection string

## Prerequisites

- **Python 3.11+**
- **Docker** (if using the `docker` backend – the default)
- **Node.js 20+** (only if building the admin frontend)

## Quick Start

### 1. Install

```bash
# Using pip
pip install -e .

# Using uv (recommended)
uv sync
```

### 2. Run

```bash
terminals serve
```

The server starts on `http://0.0.0.0:3000`. An API key is auto-generated on first run and printed to the console:

```
============================================================
  API Key: <your-generated-key>
============================================================
```

### 3. Verify

```bash
curl http://localhost:3000/health
# {"status": true}
```

### 4. Provision a terminal for a user

```bash
curl -X POST http://localhost:3000/api/v1/tenants/ \
  -H "Authorization: Bearer <your-api-key>" \
  -H "X-User-Id: user-123"
```

### 5. Proxy requests to the user's terminal

All requests to `/terminals/*` are transparently proxied to the user's Open Terminal instance:

```bash
# List files in the user's terminal
curl http://localhost:3000/terminals/files/list \
  -H "Authorization: Bearer <your-api-key>" \
  -H "X-User-Id: user-123"

# Execute a command
curl -X POST http://localhost:3000/terminals/execute \
  -H "Authorization: Bearer <your-api-key>" \
  -H "X-User-Id: user-123" \
  -H "Content-Type: application/json" \
  -d '{"command": "echo hello"}'
```

## Configuration

All settings are loaded from environment variables prefixed with `TERMINALS_`. You can also use a `.env` file in the working directory.

### Core Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINALS_API_KEY` | *(auto-generated)* | Bearer token for API auth |
| `TERMINALS_OPEN_WEBUI_URL` | | Open WebUI instance URL for JWT auth |
| `TERMINALS_DATABASE_URL` | `sqlite+aiosqlite:///./data/terminals.db` | SQLAlchemy async connection URL |
| `TERMINALS_BACKEND` | `docker` | Backend: `docker`, `kubernetes`, `kubernetes-operator`, `local`, `static` |
| `TERMINALS_PORT` | `3000` | Server bind port |
| `TERMINALS_HOST` | `0.0.0.0` | Server bind host |
| `TERMINALS_ENCRYPTION_KEY` | *(auto-generated)* | Key for encrypting stored API keys |

### Docker Backend Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINALS_IMAGE` | `ghcr.io/open-webui/open-terminal:latest` | Container image to provision |
| `TERMINALS_NETWORK` | | Docker network name (containers use IP if empty) |
| `TERMINALS_DATA_DIR` | `./data/terminals` | Host directory for per-user data volumes |

### Local Backend Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINALS_LOCAL_BINARY` | `open-terminal` | Path to the `open-terminal` binary |
| `TERMINALS_LOCAL_PORT_RANGE_START` | `9000` | First port for process allocation |

### Static Backend Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINALS_STATIC_HOST` | `127.0.0.1` | Pre-running instance host |
| `TERMINALS_STATIC_PORT` | `8000` | Pre-running instance port |
| `TERMINALS_STATIC_API_KEY` | | API key for the static instance |

### Kubernetes Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINALS_KUBERNETES_NAMESPACE` | `terminals` | K8s namespace for terminal pods |
| `TERMINALS_KUBERNETES_IMAGE` | `ghcr.io/open-webui/open-terminal:latest` | Container image |
| `TERMINALS_KUBERNETES_STORAGE_CLASS` | *(cluster default)* | PVC storage class |
| `TERMINALS_KUBERNETES_STORAGE_SIZE` | `1Gi` | PVC size per user |
| `TERMINALS_KUBERNETES_SERVICE_TYPE` | `ClusterIP` | Service type |
| `TERMINALS_KUBERNETES_KUBECONFIG` | *(in-cluster)* | Path to kubeconfig file |
| `TERMINALS_KUBERNETES_LABELS` | | Extra labels as `k=v,k2=v2` |

### Kubernetes Operator Settings

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINALS_KUBERNETES_CRD_GROUP` | `openwebui.com` | CRD API group |
| `TERMINALS_KUBERNETES_CRD_VERSION` | `v1alpha1` | CRD API version |

### Lifecycle & Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `TERMINALS_IDLE_TIMEOUT_SECONDS` | `1800` | Stop instances idle longer than this (0 = disabled) |
| `TERMINALS_CLEANUP_INTERVAL_SECONDS` | `60` | How often to sweep for idle instances |
| `TERMINALS_SIEM_WEBHOOK_URL` | | Forward audit events to this URL |

## Authentication

Terminals supports three authentication modes, determined by which environment variables are set:

### 1. Open WebUI JWT (recommended)

```bash
export TERMINALS_OPEN_WEBUI_URL=https://your-openwebui.example.com
```

Tokens are validated against the Open WebUI `/api/v1/auths/` endpoint. The verified user ID must match the `X-User-Id` header.

### 2. Static API Key

```bash
export TERMINALS_API_KEY=my-secret-key
```

Clients pass `Authorization: Bearer my-secret-key`. If no key is set, one is auto-generated on startup.

### 3. Open Access

If neither `TERMINALS_OPEN_WEBUI_URL` nor `TERMINALS_API_KEY` is set, all requests are accepted without authentication.

## Backends

### Docker (default)

Provisions one container per user via the Docker socket:

```bash
export TERMINALS_BACKEND=docker
# Ensure Docker socket is accessible
```

Each user gets an isolated container with their data mounted at `/home/user`. Containers are named `terminals-<user-id>`.

### Kubernetes

Creates a Pod + PVC + Service per user via the Kubernetes API:

```bash
export TERMINALS_BACKEND=kubernetes
export TERMINALS_KUBERNETES_NAMESPACE=terminals
# If running outside the cluster:
export TERMINALS_KUBERNETES_KUBECONFIG=~/.kube/config
```

### Kubernetes Operator

Delegates to a Kopf-based operator that watches `Terminal` CRDs:

```bash
export TERMINALS_BACKEND=kubernetes-operator
```

Deploy the operator and CRD first:

```bash
kubectl apply -f manifests/terminal-crd.yaml
kubectl apply -f manifests/operator-deployment.yaml
```

### Local

Spawns `open-terminal` as a child process per user (useful for development):

```bash
export TERMINALS_BACKEND=local
export TERMINALS_LOCAL_BINARY=open-terminal  # must be on PATH
```

### Static

Proxies all users to a single pre-running Open Terminal instance (no lifecycle management):

```bash
export TERMINALS_BACKEND=static
export TERMINALS_STATIC_HOST=127.0.0.1
export TERMINALS_STATIC_PORT=8000
export TERMINALS_STATIC_API_KEY=your-instance-api-key
```

## Docker Deployment

### Build

```bash
docker build -t terminals .
```

### Run

```bash
docker run -p 3000:3000 \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/data:/app/data \
  terminals
```

### Docker Compose

```yaml
services:
  terminals:
    build: .
    ports:
      - "3000:3000"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - terminals-data:/app/data
    environment:
      TERMINALS_API_KEY: "your-secret-key"
      # TERMINALS_OPEN_WEBUI_URL: "http://open-webui:8080"

volumes:
  terminals-data:
```

## Database

### SQLite (default)

No setup required. The database file is created automatically at `./data/terminals.db`.

### PostgreSQL

```bash
export TERMINALS_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/terminals
```

> **Note:** When using PostgreSQL, add `asyncpg` to your dependencies:
> ```bash
> pip install asyncpg
> ```

### Migrations

Migrations run automatically on startup. You can also manage them manually via the CLI:

```bash
# Run pending migrations
terminals db upgrade

# Show current revision
terminals db current

# Create a new migration
terminals db revision -m "add new column"

# Stamp DB without running migrations
terminals db stamp head
```

## Development

### Setup

```bash
# Clone and install
git clone https://github.com/open-webui/terminals.git
cd terminals
uv sync

# Start the backend in development mode
./dev.sh
# or equivalently:
uv run uvicorn terminals.main:app --reload
```

### Frontend

The admin dashboard is a SvelteKit static app:

```bash
cd terminals/frontend
npm install
npm run dev       # dev server on :5173
npm run build     # production build → build/
```

The production build is served by FastAPI at `/` when present.

### CLI Reference

```bash
terminals serve              # start the API server
terminals serve --host 0.0.0.0 --port 8080 --api-key my-key
terminals db upgrade         # run migrations
terminals db current         # show DB revision
terminals db revision -m "description"
terminals db stamp head
```

## API Reference

### Admin Endpoints (`/api/v1`)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/tenants/` | Provision a terminal (idempotent) |
| `GET` | `/api/v1/tenants/` | List all tenants |
| `GET` | `/api/v1/tenants/{user_id}` | Get a single tenant |
| `DELETE` | `/api/v1/tenants/{user_id}` | Delete tenant and instance |
| `POST` | `/api/v1/tenants/{user_id}/start` | Start a stopped tenant |
| `POST` | `/api/v1/tenants/{user_id}/stop` | Stop a tenant (keeps DB record) |
| `GET` | `/api/v1/config` | Sanitized runtime config |
| `GET` | `/api/v1/stats` | Aggregate stats for dashboard |
| `GET` | `/api/v1/audit-logs` | Query audit log history |

### Proxy Endpoints (`/terminals`)

All requests to `/terminals/{path}` are reverse-proxied to the user's Open Terminal instance. The `X-User-Id` header identifies the target tenant. Includes full support for:

- **File operations** – list, read, write, delete, move, replace, grep, glob, upload
- **Process management** – execute, status, input, kill
- **Interactive terminal** – create, list, delete sessions (WebSocket at `/terminals/api/terminals/{session_id}`)
- **Notebooks** – create, execute cells, manage sessions
- **Port proxy** – access services started within the terminal

### Other Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/terminals/openapi.json` | Open Terminal OpenAPI spec |

## License

[Open WebUI Enterprise License](LICENSE) – see LICENSE for details.
