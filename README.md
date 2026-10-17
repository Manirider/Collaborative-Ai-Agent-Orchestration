# Collaborative AI Agent Orchestration Framework

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python Version" />
  <img src="https://img.shields.io/badge/LangGraph-v0.2+-FF6F00?style=for-the-badge&logo=langchain&logoColor=white" alt="LangGraph" />
  <img src="https://img.shields.io/badge/FastAPI-0.104+-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Celery-5.3+-37814A?style=for-the-badge&logo=celery&logoColor=white" alt="Celery" />
  <img src="https://img.shields.io/badge/PostgreSQL-16+-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL" />
  <img src="https://img.shields.io/badge/Redis-7+-DC382D?style=for-the-badge&logo=redis&logoColor=white" alt="Redis" />
  <img src="https://img.shields.io/badge/Tests-36%20Passed-2EA44F?style=for-the-badge&logo=pytest&logoColor=white" alt="Test Status" />
</p>

An enterprise-grade, stateful multi-agent orchestration engine built with **LangGraph**, **FastAPI**, **Celery**, **PostgreSQL**, **Redis**, and **WebSockets**.

This system coordinates specialized autonomous agents through end-to-end research, draft synthesis, and human-in-the-loop validation pipelines. It features durable PostgreSQL checkpointing, atomic row-level concurrency protection, zero-data-loss audit telemetry, and instant initial-state WebSocket streaming.

## Table of Contents

* [System Architecture](#system-architecture)
* [Agent Workflow Lifecycle](#agent-workflow-lifecycle)
* [Key Engineering Highlights](#key-engineering-highlights)
* [API Reference](#api-reference)
* [Real-Time WebSocket Protocol](#real-time-websocket-protocol)
* [Environment Configuration](#environment-configuration)
* [Quick Start with Docker](#quick-start-with-docker)
* [Local Development & Verification](#local-development--verification)
* [Project Directory Structure](#project-directory-structure)
* [License](#license)

## System Architecture

```text
                           ┌───────────────────────────────┐
                           │    Client (HTTP / WebSocket)  │
                           └───────────────┬───────────────┘
                                           │
                                           ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                     FastAPI Gateway                                    │
│                                                                                        │
│   • REST Endpoints (/tasks, /approve, /health)                                         │
│   • WebSocket Stream with live DB snapshot & Redis Pub/Sub events                     │
│   • Concurrency Guard: Atomic row locks (SELECT ... FOR UPDATE) on approval claims     │
└───────────────────────┬────────────────────────────────────────┬───────────────────────┘
                        │                                        │
                        ▼                                        ▼
    ┌───────────────────────────────────────┐ ┌───────────────────────────────────────┐
    │       PostgreSQL 16 Database          │ │              Redis 7                  │
    │                                       │ │                                       │
    │ • Relational Tasks & Result Payloads  │ │ • Celery Message Broker & Backend     │
    │ • Complete Agent Audit Logs           │ │ • Distributed Workspace Scratchpad    │
    │ • LangGraph State Checkpoints         │ │ • Real-time Event Pub/Sub Channel     │
    │   (psycopg-pool & PostgresSaver)      │ │                                       │
    └───────────────────▲───────────────────┘ └───────────────────▲───────────────────┘
                        │                                         │
                        └───────────────────┬─────────────────────┘
                                            │
                                            ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              Celery Distributed Workers                                │
│                                                                                        │
│   LangGraph Workflow:                                                                  │
│   [ResearchAgent] ──► [WritingAgent] ──► [HumanApprovalGate] ──► [FinalizationAgent]   │
│                                                   │                                    │
│                                           (interrupt / pause)                          │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

## Agent Workflow Lifecycle

The workflow executes a sequential multi-agent state graph governed by LangGraph:

```text
 [Start]
    │
    ▼
[ResearchAgent]       Scours knowledge sources with automated transient retry handling
    │
    ▼
[WritingAgent]        Synthesizes research findings into a cohesive, structured draft
    │
    ▼
[HumanApprovalGate]   Pauses workflow via interrupt(); updates database to AWAITING_APPROVAL
    │
    ├─── (Rejected) ──► Rejection recorded with human feedback
    │
    ▼ (Approved)
[FinalizationAgent]   Incorporates reviewer notes and generates polished final deliverable
    │
    ▼
  [End]               Transitions status to COMPLETED and notifies WebSocket subscribers
```

### Lifecycle Transition Stages

1. **Submission (`POST /api/v1/tasks`)**: Creates task record with status `PENDING`, assigns a UUID, and queues an asynchronous job in Celery. Returns HTTP 202 Accepted.
2. **Worker Initialization**: Celery worker picks up the job, transitions status to `RUNNING`, writes an initial audit log, and invokes the LangGraph `StateGraph`.
3. **Research & Drafting**: `ResearchAgent` gathers factual data and `WritingAgent` drafts comparative analysis into shared workflow state.
4. **Approval Gate Interrupt**: The graph reaches `HumanApprovalGate` and executes `interrupt()`. The worker captures intermediate state, persists status `AWAITING_APPROVAL`, appends partial logs, and exits cleanly without holding worker connections.
5. **Human Review & Decision (`POST /api/v1/tasks/{id}/approve`)**: Reviewer inspects draft. Submitting approval executes an atomic row-locked database transition to `RESUMED` and dispatches Celery resumption task.
6. **Resumption & Finalization**: The worker reloads the exact checkpoint by task `thread_id`, injects human decision via `Command(resume=...)`, and runs `FinalizationAgent`.
7. **Completion**: Final output is written to PostgreSQL, status is marked `COMPLETED`, and real-time terminal notifications are published across Redis Pub/Sub.

## Key Engineering Highlights

### 1. Stateful Multi-Agent Execution
* Agents operate over a strictly typed `AgentState` TypedDict.
* State transitions are monotonic and non-destructive.
* Nodes communicate via explicit state channels rather than side effects.

### 2. Dual-Engine Resilient Checkpointing
* **Production Mode (`CHECKPOINT_MODE=postgres`)**:
  * Utilizes `langgraph-checkpoint-postgres` backed by a dedicated `psycopg_pool.ConnectionPool`.
  * Runs with connection timeouts (`connect_timeout=3`, `timeout=5.0`) to avoid silent hangs.
  * Checkpoint tables (`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`) and indexes initialize automatically before graph execution via `init_checkpoint_tables()`.
  * In production, the system fails loudly with a descriptive `RuntimeError` if PostgreSQL is unreachable, guaranteeing state durability.
* **Development / Test Mode (`CHECKPOINT_MODE=memory`)**:
  * Utilizes a thread-safe process singleton `MemorySaver` allowing rapid local iteration and 100% offline unit testing without external database dependencies.

### 3. Race-Free Human-in-the-Loop Approval Gate
* Approval endpoint utilizes database row-level locking (`with_for_update`) to prevent duplicate approval attempts and concurrent race conditions.
* Safe HTTP Status Codes:
  * `200 OK`: First valid approval claim; workflow resumed.
  * `409 Conflict`: Returned if the task is already claimed, pre-approval (`PENDING`, `RUNNING`), or completed (`COMPLETED`, `FAILED`).
  * `404 Not Found`: Returned when the task UUID does not exist.
  * `422 Unprocessable Entity`: Returned for malformed UUIDs or invalid payloads.

### 4. Non-Destructive Agent Audit Telemetry
* Logs are preserved across the entire task lifecycle (start, node completion, retry attempt, pause for approval, resume, completion, and failure).
* New log records are merged and deduplicated during status updates without overwriting previous history.

### 5. Instant Initial-State WebSocket Streaming
* Connecting WebSockets immediately receive a live database snapshot containing the current task status, agent logs, and partial results before subscribing to Redis Pub/Sub events.
* Eliminates client race conditions where events occur before subscriptions establish.

## API Reference

### 1. Create Orchestration Task
Dispatches an asynchronous multi-agent workflow.

* **Method**: `POST`
* **Endpoint**: `/api/v1/tasks`
* **Response Code**: `202 Accepted`

**Request Payload:**
```json
{
  "prompt": "Compare LangGraph vs CrewAI for stateful multi-agent systems"
}
```

**Response Payload:**
```json
{
  "task_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "PENDING",
  "message": "Task created and queued for execution"
}
```

### 2. Fetch Task Status & Audit Telemetry
Queries the latest execution state, agent activity logs, and final result.

* **Method**: `GET`
* **Endpoint**: `/api/v1/tasks/{task_id}`
* **Response Codes**: `200 OK`, `404 Not Found`, `400 Bad Request`

**Response Payload (Paused for Review):**
```json
{
  "id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "prompt": "Compare LangGraph vs CrewAI for stateful multi-agent systems",
  "status": "AWAITING_APPROVAL",
  "result": null,
  "agent_logs": [
    {"agent": "Worker", "action": "execution_started"},
    {"agent": "ResearchAgent", "action": "researched"},
    {"agent": "WritingAgent", "action": "drafted"},
    {"agent": "HumanApprovalGate", "action": "awaiting_approval"}
  ],
  "created_at": "2026-10-17T12:00:00Z",
  "updated_at": "2026-10-17T12:00:05Z"
}
```

### 3. Submit Human Approval Decision
Submits human feedback and approval to resume paused workflows.

* **Method**: `POST`
* **Endpoint**: `/api/v1/tasks/{task_id}/approve`
* **Response Codes**: `200 OK`, `409 Conflict`, `404 Not Found`, `422 Unprocessable Entity`

**Request Payload:**
```json
{
  "approved": true,
  "feedback": "Approved. Emphasize checkpoint durability and fault recovery."
}
```

**Response Payload:**
```json
{
  "task_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "RESUMED",
  "approved": true,
  "message": "Task approval decision recorded; execution resumed"
}
```

### 4. Service Health Check
* **Method**: `GET`
* **Endpoint**: `/health`
* **Response Code**: `200 OK`
* **Response Payload**: `{"status": "healthy"}`

## Real-Time WebSocket Protocol

Connect via WebSocket to stream real-time task progress:

* **URL Scheme**: `ws://localhost:8000/ws/tasks/{task_id}`

### Immediate Initial Snapshot
Upon connection, the server immediately queries PostgreSQL and returns the current task snapshot:

```json
{
  "type": "snapshot",
  "task_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "AWAITING_APPROVAL",
  "result": null,
  "agent_logs": [
    {"agent": "Worker", "action": "execution_started"},
    {"agent": "ResearchAgent", "action": "researched"},
    {"agent": "WritingAgent", "action": "drafted"},
    {"agent": "HumanApprovalGate", "action": "awaiting_approval"}
  ]
}
```

### Live Event Broadcasts
Subsequent status changes published over Redis Pub/Sub are streamed directly to connected clients:

```json
{
  "type": "event",
  "task_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "status": "COMPLETED",
  "timestamp": "2026-10-17T12:01:10Z"
}
```

## Environment Configuration

Configure the platform through `.env` or system environment variables:

* `APP_ENV`: Application mode (`development` or `production`). Default: `development`.
* `CHECKPOINT_MODE`: Checkpointing persistence strategy:
  * `postgres`: Production mode backed by PostgreSQL (`langgraph-checkpoint-postgres`).
  * `memory`: In-memory checkpointer for local development and offline unit testing.
  * `auto`: Automatically uses PostgreSQL if reachable; falls back to memory in development. Default: `auto`.
* `DATABASE_URL`: PostgreSQL async connection string. Default: `postgresql+asyncpg://postgres:postgres@db:5432/ai_orchestration`.
* `REDIS_URL`: Redis connection URL for distributed scratchpad and Pub/Sub. Default: `redis://redis:6379/0`.
* `CELERY_BROKER_URL`: Celery broker connection string. Default: `redis://redis:6379/1`.
* `CELERY_RESULT_BACKEND`: Celery task result backend. Default: `redis://redis:6379/2`.
* `TASK_MAX_RETRIES`: Maximum retry attempts for transient worker failures. Default: `3`.
* `TASK_RETRY_BACKOFF_SECONDS`: Countdown delay between worker task retries. Default: `2`.

## Quick Start with Docker

### Prerequisites
* Docker Engine 24.0+
* Docker Compose v2.20+

### Step 1: Clone & Configure
```bash
cp .env.example .env
```

### Step 2: Build & Start Services
```bash
docker compose up --build -d
```

### Step 3: Verify Container Health
```bash
docker compose ps
```

### Step 4: Stream Worker Logs
```bash
docker compose logs -f api worker
```

Exposed Services:
* FastAPI REST API & WebSockets: `http://localhost:8000`
* PostgreSQL Database: `localhost:5432`
* Redis Message Broker: `localhost:6379`

## Local Development & Verification

### 1. Local Environment Setup
```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Verify Code Compilation
Ensure all modules compile cleanly:
```bash
python -m compileall src tests
```

### 3. Run Test Suite (100% Offline / SQLite / Mock)
Execute the complete test suite without requiring external databases or services:
```bash
python -m pytest -q tests
```
*Current Suite Status: 36 passed, 1 skipped, 0 warnings.*

### 4. Run Live Container Integration Tests
Execute integration tests against running PostgreSQL and Redis containers:
```bash
docker compose up -d db redis
pytest -v -m integration tests
```

## Project Directory Structure

```text
.
├── src/
│   ├── agents/
│   │   ├── checkpointing.py      # PostgresSaver connection pool & MemorySaver factory
│   │   ├── graph.py              # LangGraph StateGraph, agent nodes & conditional routing
│   │   ├── state.py              # TypedDict agent state definitions
│   │   └── tools.py              # Agent research tools with transient failure simulation
│   ├── api/
│   │   ├── app.py                # FastAPI factory, lifespan management & routing
│   │   ├── routes.py             # Task CRUD and atomic approval endpoints
│   │   └── websocket.py          # WebSocket handler with initial DB snapshot delivery
│   ├── config/
│   │   └── settings.py           # Pydantic v2 application settings and validation
│   ├── db/
│   │   ├── models.py             # SQLAlchemy models with dual PostgreSQL/SQLite support
│   │   └── session.py            # Async engine and dynamic session manager
│   ├── observability/
│   │   └── logging.py            # Structured JSON logger and redaction utilities
│   ├── services/
│   │   ├── event_service.py      # Redis Pub/Sub task event broadcaster
│   │   ├── task_service.py       # Task persistence, atomic approval lock, status updates
│   │   └── workspace_service.py  # Shared Redis scratchpad for multi-agent data exchange
│   └── worker/
│       ├── celery_app.py         # Celery application initialization
│       └── tasks.py              # Celery tasks: execute_graph and resume_graph
├── tests/
│   ├── conftest.py               # Fixtures for SQLite isolation and Celery mocking
│   ├── test_agent_graph.py       # LangGraph interruption, approval, and isolation tests
│   ├── test_database.py          # Database operations, atomic claims, and model variants
│   ├── test_health.py            # Service healthcheck endpoint verification
│   ├── test_human_approval.py    # Approval API contracts (200, 409 Conflict, 404, 400)
│   ├── test_integration.py       # Full lifecycle worker tests and PostgresSaver integration
│   ├── test_retry.py             # Worker retry mechanics, backoff, and secret masking
│   ├── test_task_api.py          # Task creation and query API tests
│   ├── test_websocket.py         # WebSocket initial snapshot and event delivery tests
│   └── test_workspace.py         # Workspace scratchpad persistence tests
├── docker-compose.yml            # Multi-service stack definition (API, Worker, DB, Redis)
├── Dockerfile                    # Container definition with healthcheck support
├── pytest.ini                    # Pytest settings and deprecation warning filters
├── requirements.txt              # Core project dependencies
└── README.md                     # Project documentation
```

## License

This project is licensed under the Apache 2.0 License.
