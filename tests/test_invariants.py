"""Invariant, validation and scenario-sweep tests for the CascadeLens prototype."""
import itertools

import pytest
from fastapi.testclient import TestClient

from app.data import build_network
from app.main import app
from app.simulator import (FAILED, ON_BACKUP, OPERATIONAL, SEVERITY_REPAIR_MULTIPLIER,
                           Intervention, Scenario, candidate_interventions, check_feasibility,
                           explain, rank_options, simulate)

NET = build_network()
STATES = {OPERATIONAL, ON_BACKUP, FAILED}
client = TestClient(app)


def compare_rows(scenario):
    baseline = simulate(NET, scenario)
    rows = []
    for iv in candidate_interventions(NET, scenario, baseline):
        row = {"label": iv.label(NET), "kind": iv.kind, "cost": iv.cost, "feasible": True}
        reason = check_feasibility(NET, scenario, iv)
        if reason:
            row.update(feasible=False, reason=reason)
        else:
            row["impact"] = simulate(NET, scenario, (iv,)).impact
        rows.append(row)
    return baseline, rank_options(NET, baseline, rows)


def test_network_data_is_consistent():
    for e in NET.edges.values():
        assert e.supplier in NET.assets and e.dependent in NET.assets
        assert e.supplier != e.dependent and e.load > 0
    for a in NET.assets.values():
        assert a.repair_hours > 0 and a.backup_hours >= 0 and a.people_served >= 0
        active_load = sum(e.load for e in NET.edges.values() if e.supplier == a.id and e.active)
        if a.type == "substation":
            assert active_load <= a.capacity, f"{a.id} over-subscribed by default"
    assert len({(a.x, a.y) for a in NET.assets.values()}) == len(NET.assets), "overlapping nodes"


@pytest.mark.parametrize("asset_id,severity", list(itertools.product(
    sorted(NET.assets), sorted(SEVERITY_REPAIR_MULTIPLIER))))
def test_every_single_failure_respects_invariants(asset_id, severity):
    scenario = Scenario("storm", severity, (asset_id,), 72)
    r = simulate(NET, scenario)
    assert len(r.timeline) == 73 and [s["t"] for s in r.timeline] == list(range(73))
    for snap in r.timeline:
        assert set(snap["states"]) == set(NET.assets)
        assert set(snap["states"].values()) <= STATES
    assert r.timeline[0]["states"][asset_id] == FAILED
    hours = [e["t"] for e in r.ledger]
    assert hours == sorted(hours) and [e["id"] for e in r.ledger] == list(range(1, len(hours) + 1))
    for e in r.ledger:
        if e["type"] != "intervention":
            assert e["from"] != e["to"] or e["cause"] == "repair completed"
    imp = r.impact
    assert imp["total_unserved_service_person_hours"] == sum(
        imp["unserved_person_hours_by_service"].values())
    assert imp["critical_facility_outage_hours"] >= 0 and imp["peak_assets_failed"] >= 1
    if imp["recovered_within_horizon"]:
        assert all(s == OPERATIONAL for s in r.timeline[imp["recovery_hour"]]["states"].values())
    else:
        assert any(s != OPERATIONAL for s in r.timeline[-1]["states"].values())
    # Backup is only ever drawn down; nobody ends up better than they started.
    backup_events = [e for e in r.ledger if e["to"] == ON_BACKUP]
    for e in backup_events:
        assert NET.assets[e["asset"]].backup_hours > 0


def test_repair_time_scales_with_severity():
    hours = {}
    for sev in SEVERITY_REPAIR_MULTIPLIER:
        r = simulate(NET, Scenario("flood", sev, ("S1",), 72))
        hours[sev] = next(e["t"] for e in r.ledger if e["asset"] == "S1" and e["to"] == OPERATIONAL)
    assert hours == {"low": 24, "medium": 36, "high": 48}


def test_multi_failure_is_at_least_as_bad_as_each_single_failure():
    both = simulate(NET, Scenario("flood", "medium", ("S1", "S3"), 48)).impact
    for single in ("S1", "S3"):
        one = simulate(NET, Scenario("flood", "medium", (single,), 48)).impact
        assert both["total_unserved_service_person_hours"] >= one["total_unserved_service_person_hours"]
        assert both["critical_facility_outage_hours"] >= one["critical_facility_outage_hours"]
    # S3 loss also starves the treatment plant, which cascades into both pump stations.
    r = simulate(NET, Scenario("flood", "medium", ("S3",), 48))
    assert r.timeline[1]["states"]["W1"] == ON_BACKUP
    assert r.timeline[3]["states"]["W1"] == FAILED
    assert r.timeline[4]["states"]["P2"] == FAILED


def test_backup_intervention_restores_shelter_and_then_runs_out():
    scenario = Scenario("flood", "high", ("S1",), 48)
    r = simulate(NET, scenario, (Intervention("backup", "SH1", 12),))
    states = [snap["states"]["SH1"] for snap in r.timeline]
    assert states[1] == FAILED  # generator not delivered yet
    assert all(s == ON_BACKUP for s in states[2:14])  # 12 hours of generator power
    assert states[14] == FAILED  # fuel exhausted before the 48h repair
    delivered = next(e for e in r.ledger if e["type"] == "intervention" and e["asset"] == "SH1")
    assert delivered["t"] == 2 and "+12h" in delivered["rule"]


def test_alternate_supply_shows_in_timeline_and_helps_telecom():
    scenario = Scenario("flood", "medium", ("S1",), 48)
    r = simulate(NET, scenario, (Intervention("alternate", "ALT-S3-T1"),))
    assert "ALT-S3-T1" not in r.timeline[0]["active_edges"]
    assert "ALT-S3-T1" in r.timeline[1]["active_edges"]
    assert all(snap["states"]["T1"] != FAILED for snap in r.timeline)
    assert "telecom" not in r.impact["unserved_person_hours_by_service"]


@pytest.mark.parametrize("failed", [("S1",), ("S2",), ("S3",), ("W1",), ("S1", "S2"), ("H1",)])
def test_ranking_is_well_formed_for_varied_scenarios(failed):
    scenario = Scenario("storm", "medium", failed, 48)
    baseline, ranked = compare_rows(scenario)
    feasible = [r for r in ranked if r["feasible"]]
    assert [r["rank"] for r in feasible] == list(range(1, len(feasible) + 1))
    assert all(a["score"] >= b["score"] for a, b in zip(feasible, feasible[1:]))
    assert any(r["kind"] == "baseline" for r in feasible)
    for r in ranked:
        if r["feasible"]:
            assert r["impact"]["total_unserved_service_person_hours"] >= 0
        else:
            assert r["reason"]
    text = explain(NET, scenario, baseline, ranked)
    assert "Hour 0" in text and "planner review" in text


def test_every_candidate_flagged_feasible_actually_simulates():
    for failed in (("S1",), ("S2",), ("S3",), ("S1", "S3")):
        scenario = Scenario("flood", "low", failed, 24)
        baseline = simulate(NET, scenario)
        for iv in candidate_interventions(NET, scenario, baseline):
            if check_feasibility(NET, scenario, iv) is None:
                simulate(NET, scenario, (iv,))  # must not raise


@pytest.mark.parametrize("body,expected", [
    ({"failed_assets": []}, 422),
    ({"failed_assets": ["S1"], "severity": "extreme"}, 422),
    ({"failed_assets": ["S1"], "horizon_hours": 0}, 422),
    ({"failed_assets": ["S1"], "horizon_hours": 999}, 422),
    ({"failed_assets": ["S1"], "hazard": ""}, 422),
    ({"failed_assets": ["S1"] * 11}, 422),
    ({"failed_assets": ["S1", "ZZ"]}, 400),
    ({}, 422),
])
def test_api_rejects_bad_input(body, expected):
    assert client.post("/api/simulate", json=body).status_code == expected
    assert client.post("/api/compare", json=body).status_code == expected


def test_api_deduplicates_assets_and_matches_engine():
    body = {"failed_assets": ["S2", "S2"], "severity": "low", "horizon_hours": 30}
    api = client.post("/api/simulate", json=body).json()
    engine = simulate(NET, Scenario("flood", "low", ("S2",), 30))
    assert api["impact"] == engine.impact
    assert len([e for e in api["ledger"] if e["type"] == "hazard"]) == 1


def test_api_network_and_static_assets():
    net = client.get("/api/network").json()
    assert {a["id"] for a in net["assets"]} == set(NET.assets)
    assert sum(1 for e in net["edges"] if not e["active"]) == 3
    page = client.get("/")
    assert page.status_code == 200 and "CascadeLens prototype" in page.text
    for endpoint in ("/api/network", "/api/simulate", "/api/compare"):
        assert endpoint in client.get("/openapi.json").text
