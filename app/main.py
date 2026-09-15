from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.data import build_network
from app.simulator import (Intervention, Scenario, candidate_interventions, check_feasibility,
                           explain, rank_options, simulate)

NETWORK = build_network()
STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="CascadeLens prototype", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class ScenarioRequest(BaseModel):
    hazard: str = Field("flood", min_length=1, max_length=40)
    severity: Literal["low", "medium", "high"] = "medium"
    failed_assets: list[str] = Field(min_length=1, max_length=10)
    horizon_hours: int = Field(48, ge=1, le=168)


def to_scenario(req: ScenarioRequest) -> Scenario:
    unknown = [a for a in req.failed_assets if a not in NETWORK.assets]
    if unknown:
        raise HTTPException(400, f"unknown asset ids: {unknown}")
    return Scenario(req.hazard, req.severity, tuple(dict.fromkeys(req.failed_assets)),
                    req.horizon_hours)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/network")
def network():
    return {"assets": [vars(a) for a in NETWORK.assets.values()],
            "edges": [vars(e) for e in NETWORK.edges.values()]}


@app.post("/api/simulate")
def run_simulation(req: ScenarioRequest):
    result = simulate(NETWORK, to_scenario(req))
    return {"ledger": result.ledger, "timeline": result.timeline, "impact": result.impact}


@app.post("/api/compare")
def compare(req: ScenarioRequest):
    scenario = to_scenario(req)
    baseline = simulate(NETWORK, scenario)
    options = []
    for iv in candidate_interventions(NETWORK, scenario, baseline):
        row = {"label": iv.label(NETWORK), "kind": iv.kind, "target": iv.target,
               "cost": iv.cost, "feasible": True}
        reason = check_feasibility(NETWORK, scenario, iv)
        if reason:
            row.update(feasible=False, reason=reason)
        else:
            row["impact"] = simulate(NETWORK, scenario, (iv,)).impact
        options.append(row)
    ranked = rank_options(NETWORK, baseline, options)
    return {"baseline_impact": baseline.impact, "options": ranked,
            "explanation": explain(NETWORK, scenario, baseline, ranked)}
