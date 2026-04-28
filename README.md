# PDS360 AI Platform

This repository now includes a full-stack application structure for the Andhra Pradesh PDS AI Hackathon use cases:

- SMARTAllot
- Anomaly Detection
- PDSAIBot
- AI-enabled Call Centre

## Stack

- Backend: `Python + FastAPI + SQLAlchemy`
- Database: `PostgreSQL`
- Frontend: `React + TypeScript + Vite + React Query + React Router`
- Local orchestration: `Docker Compose`

## Project Structure

- [backend](C:\Users\S Sameer\Desktop\pds system\backend)
- [frontend](C:\Users\S Sameer\Desktop\pds system\frontend)
- [docker-compose.yml](C:\Users\S Sameer\Desktop\pds system\docker-compose.yml)
- [SRS.md](C:\Users\S Sameer\Desktop\pds system\SRS.md)
- [IMPLEMENTATION_ROADMAP.md](C:\Users\S Sameer\Desktop\pds system\IMPLEMENTATION_ROADMAP.md)

## Backend Run

```powershell
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Or use:

```powershell
cd backend
.\run_backend.ps1
```

## Frontend Run

```powershell
cd frontend
npm install
npm run dev
```

Or use:

```powershell
cd frontend
.\run_frontend.ps1
```

## Docker Run

```powershell
docker compose up --build
```

The PostgreSQL service is exposed on host port `5433` to avoid collisions with any existing local Postgres instance.

## Start Both

From the [backend](C:\Users\S Sameer\Desktop\pds system\backend) folder:

```powershell
.\start_all.ps1
```

This starts:
- PostgreSQL container if Docker is available
- FastAPI backend in a new PowerShell window
- React frontend in a new PowerShell window

## Core API Endpoints

- `GET /health`
- `GET /api/dashboard/overview`
- `GET /api/smart-allot/recommendations`
- `GET /api/smart-allot/summary`
- `GET /api/anomalies`
- `GET /api/anomalies/summary`
- `POST /api/bot/query`
- `GET /api/call-centre/tickets`
- `GET /api/call-centre/summary`

## Notes

- The backend seeds PostgreSQL with sample records on startup so the full UI has immediate demo data.
- The earlier lightweight Node prototype remains in the root `src` folder as reference material, but the main application stack is now `backend` + `frontend`.
