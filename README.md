# GROCERY ERP PRO

Enterprise multi-tenant SaaS grocery ERP delivered as a **native Windows EXE**
(PySide6), with per-installation independent **SQLite** databases, offline-first
operations, a dedicated **background synchronization engine**, and a centralized
**signed application update system**. The cloud backend is a Python
**Django + DRF** modular monolith on PostgreSQL/Redis/Celery.

There is **no customer-facing web frontend**: the Windows EXE is the only
business interface, including the Super Admin workspace.

## Layout
- `backend/` — Django REST cloud backend (`config/`, `apps/`, `tests/`)
- `desktop/` — native PySide6 client (`database/`, `business_logic/`,
  `synchronization/`, `updates/`, `security/`, `ui/`, `packaging/`, `tests/`)
- `infrastructure/` — Docker, Nginx, deployment, update storage, backups
- `documentation/` — architecture, database, API, security, sync, updates, guides
- `scripts/` — development and release scripts

## Quick start (development)
```bash
pip install -r backend/requirements.txt
cd backend && python manage.py migrate && python manage.py runserver
cd desktop && pytest -q            # desktop tests (pure-Python core, no Qt required)
cd backend && pytest -q            # backend tests
```

## Status
See `documentation/architecture/STATUS.md` for the phase-by-phase delivery
status, evidence, and remaining production-readiness tasks.
