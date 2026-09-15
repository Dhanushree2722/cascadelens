# CascadeLens prototype

Simple working prototype: simulate how one infrastructure failure cascades through a
synthetic city, trace every state change in an evidence ledger, and compare interventions.

```powershell
cd cascadelens
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000, pick failed assets, run, drag the hour slider, then
"Compare interventions".

- Data: `app/data.py` (20 synthetic assets, dependencies, inactive alternate links)
- Rules: `app/simulator.py` (synchronous hourly steps, backups, repairs, capacity checks, ranking)
- API: `app/main.py` (`/api/network`, `/api/simulate`, `/api/compare`)
- UI: `static/index.html`

Limitations: synthetic data, simplified rules, template explanation (no LLM), in-memory only.
Not validated for real emergency operations.
