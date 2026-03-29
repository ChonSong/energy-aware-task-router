# Energy-Aware Task Router

Data infrastructure is also an energy infrastructure story. Data centers are straining electricity grids; compute demand is growing faster than renewable capacity can absorb it. Most systems treat energy as a background concern. This project treats it as a first-class constraint.

Built a task routing system that queries real-time carbon intensity of the electricity grid and routes deferrable compute to low-intensity windows — without breaking user-facing SLAs. When carbon data is unavailable, the system falls back gracefully and logs the gap. Every routing decision is logged with the grid conditions at the time, so tradeoffs are auditable after the fact.

## Features

- **Real-time carbon intensity queries** via electricitymap.org API (or compatible)
- **SLA-preserving routing** — user-facing deadlines are never sacrificed for green credentials
- **Graceful degradation** — when carbon data is unavailable, logs the gap and continues
- **Audit trail** — every routing decision recorded with grid conditions, timestamps, and rationale
- **Configurable deferral windows** — specify which task types are eligible for deferral

## Quick Start

```bash
pip install -e .
export CARBON_API_KEY=your_electricitymap_api_key

python -m energy_router serve --config config.example.yaml
```

## Tech Stack

- **Python 3.11+** — FastAPI, httpx, structlog, PyYAML