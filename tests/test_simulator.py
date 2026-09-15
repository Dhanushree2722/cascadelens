import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.data import build_network
from app.main import app
from app.simulator import (FAILED, ON_BACKUP, OPERATIONAL, Asset, Edge, Intervention, Network,
                           Scenario, candidate_interventions, check_feasibility, rank_options,
                           simulate)

NET = build_network()
S1_FLOOD = Scenario("flood", "medium", ("S1",), 48)


def states_at(result, t):
    return result.timeline[t]["states"]


def test_failure_propagates_only_through_dependencies():
    r = simulate(NET, S1_FLOOD)
    hour1 = states_at(r, 1)
    assert hour1["S1"] == FAILED
    assert hour1["R1"] == FAILED  # needs S1 power, no backup
    assert hour1["H1"] == ON_BACKUP  # needs S1 power, has 8h backup
    assert hour1["P1"] == FAILED  # loses power -> water for north stops next hour
    assert states_at(r, 2)["SH1"] == FAILED
    for unaffected in ("S2", "S3", "R3", "R5", "H2", "T3"):
        assert all(snap["states"][unaffected] == OPERATIONAL for snap in r.timeline)


def test_backup_delays_failure_for_configured_duration():
    r = simulate(NET, S1_FLOOD)
    assert all(states_at(r, t)["T1"] == ON_BACKUP for t in range(1, 5))
    assert states_at(r, 5)["T1"] == FAILED
    event = next(e for e in r.ledger if e["asset"] == "T1" and e["to"] == FAILED)
    assert event["t"] == 5 and "backup exhausted" in event["rule"]


def test_repair_restores_service_and_dependents_recover():
    r = simulate(NET, S1_FLOOD)
    assert states_at(r, 36)["S1"] == OPERATIONAL  # 24h * 1.5 medium severity
    assert states_at(r, 35)["S1"] == FAILED
    assert states_at(r, 37)["P1"] == OPERATIONAL  # pump needs S1 power first
    assert states_at(r, 37)["R1"] == FAILED  # feeder still waiting for P1 water
    assert states_at(r, 38)["R1"] == OPERATIONAL
    assert r.impact["recovered_within_horizon"] and r.impact["recovery_hour"] == 38


def test_expedited_repair_reduces_impact():
    base = simulate(NET, S1_FLOOD)
    fast = simulate(NET, S1_FLOOD, (Intervention("repair", "S1", 6),))
    assert states_at(fast, 6)["S1"] == OPERATIONAL
    assert (fast.impact["total_unserved_service_person_hours"]
            < base.impact["total_unserved_service_person_hours"])


def test_identical_inputs_give_identical_results():
    a, b = simulate(NET, S1_FLOOD), simulate(NET, S1_FLOOD)
    assert a.ledger == b.ledger and a.timeline == b.timeline and a.impact == b.impact


def test_alternate_supply_capacity_check():
    assert "overloaded" in check_feasibility(NET, S1_FLOOD, Intervention("alternate", "ALT-S2-H1"))
    assert check_feasibility(NET, S1_FLOOD, Intervention("alternate", "ALT-S3-P1")) is None
    with pytest.raises(ValueError):
        simulate(NET, S1_FLOOD, (Intervention("alternate", "ALT-S2-H1"),))
    r = simulate(NET, S1_FLOOD, (Intervention("alternate", "ALT-S3-P1"),))
    assert states_at(r, 2)["P1"] == OPERATIONAL  # switched on at hour 1, effective hour 2


def test_infeasible_interventions_are_rejected():
    assert check_feasibility(NET, S1_FLOOD, Intervention("repair", "S2", 6))
    assert check_feasibility(NET, S1_FLOOD, Intervention("backup", "S1", 12))
    assert check_feasibility(NET, Scenario("flood", "medium", ("S3",)),
                             Intervention("alternate", "ALT-S3-P1")) == "alternate supplier is itself damaged"


def test_baseline_ranks_first_when_intervention_has_no_benefit():
    base = simulate(NET, S1_FLOOD)
    useless = Intervention("backup", "H2", 12)  # H2 is unaffected by an S1 failure
    row = {"label": "x", "kind": "backup", "cost": useless.cost, "feasible": True,
           "impact": simulate(NET, S1_FLOOD, (useless,)).impact}
    ranked = rank_options(NET, base, [row])
    assert ranked[0]["kind"] == "baseline"


def test_cyclic_dependencies_terminate():
    assets = {i: Asset(i, i, "pump", "water", 10, 100, 0, 5, 0, 0) for i in ("A", "B")}
    edges = {"A-B": Edge("A-B", "A", "B", 1), "B-A": Edge("B-A", "B", "A", 1)}
    graph = nx.DiGraph([("A", "B"), ("B", "A")])
    r = simulate(Network(assets, edges, graph), Scenario("fault", "low", ("A",), 12))
    assert len(r.timeline) == 13
    assert not r.impact["recovered_within_horizon"]  # deadlock is reported, not hidden


def test_candidates_cover_repair_backup_and_alternates():
    base = simulate(NET, S1_FLOOD)
    kinds = {iv.kind for iv in candidate_interventions(NET, S1_FLOOD, base)}
    assert kinds == {"repair", "backup", "alternate"}


def test_api_end_to_end():
    client = TestClient(app)
    assert len(client.get("/api/network").json()["assets"]) == 20
    body = {"hazard": "flood", "severity": "high", "failed_assets": ["S1"], "horizon_hours": 48}
    sim = client.post("/api/simulate", json=body).json()
    assert sim["ledger"][0]["type"] == "hazard" and len(sim["timeline"]) == 49
    cmp = client.post("/api/compare", json=body).json()
    assert cmp["options"][0]["rank"] == 1
    assert any(not o["feasible"] for o in cmp["options"])
    assert "event" in cmp["explanation"]
    assert client.post("/api/simulate", json={"failed_assets": ["NOPE"]}).status_code == 400
    assert client.get("/").status_code == 200
