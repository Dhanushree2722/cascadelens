"""Deterministic, time-stepped cascade simulator with an evidence ledger.

Rules are applied synchronously each hour from the previous hour's states, so
results do not depend on the order in which assets are processed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import networkx as nx

OPERATIONAL, ON_BACKUP, FAILED = "operational", "on_backup", "failed"
CRITICAL_TYPES = {"hospital", "shelter", "eoc"}
SEVERITY_REPAIR_MULTIPLIER = {"low": 1.0, "medium": 1.5, "high": 2.0}

INTERVENTION_COST = {"repair": 40000, "backup": 1500, "alternate": 20000}
INTERVENTION_DELAY_HOURS = {"repair": 0, "backup": 2, "alternate": 1}
SCORE_WEIGHTS = {"unserved": 60, "critical": 30, "cost": 10}


@dataclass(frozen=True)
class Asset:
    id: str
    name: str
    type: str
    service: str
    capacity: float
    people_served: int
    backup_hours: int
    repair_hours: int
    x: int
    y: int


@dataclass(frozen=True)
class Edge:
    id: str
    supplier: str
    dependent: str
    load: float
    active: bool = True


@dataclass(frozen=True)
class Network:
    assets: dict[str, Asset]
    edges: dict[str, Edge]
    graph: nx.DiGraph


@dataclass(frozen=True)
class Scenario:
    hazard: str
    severity: str
    failed_assets: tuple[str, ...]
    horizon_hours: int = 48


@dataclass(frozen=True)
class Intervention:
    kind: str  # repair | backup | alternate
    target: str  # asset id for repair/backup, edge id for alternate
    hours: int = 0

    @property
    def cost(self) -> int:
        unit = INTERVENTION_COST[self.kind]
        return unit * self.hours if self.kind == "backup" else unit

    def label(self, network: Network) -> str:
        if self.kind == "repair":
            return f"Expedite repair of {network.assets[self.target].name} ({self.hours}h)"
        if self.kind == "backup":
            return f"Deploy {self.hours}h backup power to {network.assets[self.target].name}"
        edge = network.edges[self.target]
        return (f"Activate alternate supply {network.assets[edge.supplier].name} -> "
                f"{network.assets[edge.dependent].name}")


@dataclass
class SimulationResult:
    ledger: list[dict] = field(default_factory=list)
    timeline: list[dict] = field(default_factory=list)
    impact: dict = field(default_factory=dict)


def check_feasibility(network: Network, scenario: Scenario, iv: Intervention) -> str | None:
    """Return a rejection reason, or None when the intervention can be applied."""
    if iv.kind == "repair":
        if iv.target not in scenario.failed_assets:
            return "asset is not damaged in this scenario"
        default = math.ceil(network.assets[iv.target].repair_hours
                            * SEVERITY_REPAIR_MULTIPLIER[scenario.severity])
        if iv.hours <= 0 or iv.hours >= default:
            return f"not faster than the default repair ({default}h)"
        return None
    if iv.kind == "backup":
        asset = network.assets.get(iv.target)
        if asset is None:
            return "unknown asset"
        if asset.type == "substation":
            return "temporary generators cannot replace a substation"
        if not 1 <= iv.hours <= 48:
            return "backup duration must be 1-48 hours"
        return None
    if iv.kind == "alternate":
        edge = network.edges.get(iv.target)
        if edge is None or edge.active:
            return "no inactive alternate connection with this id"
        if edge.supplier in scenario.failed_assets:
            return "alternate supplier is itself damaged"
        supplier = network.assets[edge.supplier]
        load = sum(e.load for e in network.edges.values()
                   if e.supplier == edge.supplier and e.active) + edge.load
        if load > supplier.capacity:
            return (f"{supplier.name} would be overloaded "
                    f"({load:g} > capacity {supplier.capacity:g})")
        return None
    return f"unknown intervention kind '{iv.kind}'"


def simulate(network: Network, scenario: Scenario,
             interventions: tuple[Intervention, ...] = ()) -> SimulationResult:
    assets = network.assets
    result = SimulationResult()
    status = {a: OPERATIONAL for a in assets}
    backup_left = {a: assets[a].backup_hours for a in assets}
    repair_due: dict[str, int] = {}
    active = {e.id: e.active for e in network.edges.values()}
    multiplier = SEVERITY_REPAIR_MULTIPLIER[scenario.severity]

    def log(t, asset, old, new, cause, rule, kind="state"):
        result.ledger.append({"id": len(result.ledger) + 1, "t": t, "type": kind,
                              "asset": asset, "asset_name": assets[asset].name,
                              "from": old, "to": new, "cause": cause, "rule": rule})

    for aid in scenario.failed_assets:
        status[aid] = FAILED
        repair_due[aid] = math.ceil(assets[aid].repair_hours * multiplier)
        log(0, aid, OPERATIONAL, FAILED, f"{scenario.hazard} ({scenario.severity} severity)",
            f"hazard damage; default repair completes at hour {repair_due[aid]}", "hazard")

    scheduled: list[tuple[int, Intervention]] = []
    for iv in interventions:
        reason = check_feasibility(network, scenario, iv)
        if reason:
            raise ValueError(f"infeasible intervention {iv}: {reason}")
        if iv.kind == "repair":
            repair_due[iv.target] = iv.hours
            log(0, iv.target, FAILED, FAILED, "intervention: expedited repair",
                f"repair now completes at hour {iv.hours}", "intervention")
        else:
            scheduled.append((INTERVENTION_DELAY_HOURS[iv.kind], iv))

    def missing_services(aid: str, prev: dict[str, str]) -> list[str]:
        needed: dict[str, bool] = {}
        for e in network.edges.values():
            if e.dependent != aid or not active[e.id]:
                continue
            service = assets[e.supplier].service
            needed[service] = needed.get(service, False) or prev[e.supplier] != FAILED
        return sorted(s for s, ok in needed.items() if not ok)

    def snapshot(t):
        result.timeline.append({"t": t, "states": dict(status),
                                "active_edges": [e for e, on in active.items() if on]})

    snapshot(0)
    unserved: dict[str, float] = {}
    critical_hours = 0
    recovery_hour = None
    peak_failed = sum(1 for s in status.values() if s == FAILED)

    for t in range(1, scenario.horizon_hours + 1):
        for when, iv in scheduled:
            if when != t:
                continue
            if iv.kind == "backup":
                backup_left[iv.target] += iv.hours
                log(t, iv.target, status[iv.target], status[iv.target],
                    "intervention: temporary generator delivered",
                    f"+{iv.hours}h backup ({backup_left[iv.target]}h available)", "intervention")
            else:
                active[iv.target] = True
                edge = network.edges[iv.target]
                log(t, edge.dependent, status[edge.dependent], status[edge.dependent],
                    "intervention: alternate supply switched on",
                    f"edge {iv.target} activated within {assets[edge.supplier].name} capacity",
                    "intervention")

        prev = dict(status)
        for aid in assets:
            cur = prev[aid]
            if aid in repair_due:
                if t < repair_due[aid]:
                    continue
                del repair_due[aid]
                cause, restored = "repair completed", True
            else:
                cause, restored = "", False
            missing = missing_services(aid, prev)
            if not missing:
                if cur != OPERATIONAL or restored:
                    status[aid] = OPERATIONAL
                    log(t, aid, cur, OPERATIONAL, cause or "upstream supply restored",
                        "all required services available")
                continue
            need = ", ".join(missing)
            if backup_left[aid] > 0:
                backup_left[aid] -= 1
                status[aid] = ON_BACKUP
                if cur != ON_BACKUP:
                    log(t, aid, cur, ON_BACKUP, f"lost {need} supply",
                        f"running on backup ({backup_left[aid] + 1}h remaining)")
            else:
                status[aid] = FAILED
                if cur != FAILED or restored:
                    why = "backup exhausted" if assets[aid].backup_hours else "no backup"
                    log(t, aid, cur, FAILED, f"lost {need} supply", f"{why}; service stops")

        snapshot(t)
        failed_now = 0
        for aid, s in status.items():
            if s != FAILED:
                continue
            failed_now += 1
            asset = assets[aid]
            unserved[asset.service] = unserved.get(asset.service, 0) + asset.people_served
            if asset.type in CRITICAL_TYPES:
                critical_hours += 1
        peak_failed = max(peak_failed, failed_now)
        if recovery_hour is None and all(s == OPERATIONAL for s in status.values()):
            recovery_hour = t

    result.impact = {
        "unserved_person_hours_by_service": {k: v for k, v in sorted(unserved.items()) if v},
        "total_unserved_service_person_hours": sum(unserved.values()),
        "critical_facility_outage_hours": critical_hours,
        "peak_assets_failed": peak_failed,
        "recovery_hour": recovery_hour,
        "recovered_within_horizon": recovery_hour is not None,
    }
    return result


def candidate_interventions(network: Network, scenario: Scenario,
                            baseline: SimulationResult) -> list[Intervention]:
    affected = {e["asset"] for e in baseline.ledger if e["to"] != OPERATIONAL}
    options = [Intervention("repair", a, 6) for a in scenario.failed_assets]
    options += [Intervention("backup", a, 12) for a in sorted(affected)
                if network.assets[a].type in CRITICAL_TYPES]
    options += [Intervention("alternate", e.id) for e in network.edges.values() if not e.active]
    return options


def rank_options(network: Network, baseline: SimulationResult, options: list[dict]) -> list[dict]:
    """Transparent weighted score; the no-action baseline competes on equal terms."""
    base_unserved = baseline.impact["total_unserved_service_person_hours"]
    base_critical = baseline.impact["critical_facility_outage_hours"]
    rows = [{"label": "No action (baseline)", "kind": "baseline", "cost": 0,
             "feasible": True, "impact": baseline.impact}] + options
    max_cost = max((r["cost"] for r in rows if r["feasible"]), default=0) or 1
    for row in rows:
        if not row["feasible"]:
            row["score"] = None
            continue
        impact = row["impact"]
        avoided_unserved = ((base_unserved - impact["total_unserved_service_person_hours"])
                            / base_unserved if base_unserved else 0)
        avoided_critical = ((base_critical - impact["critical_facility_outage_hours"])
                            / base_critical if base_critical else 0)
        row["avoided_unserved_pct"] = round(100 * avoided_unserved, 1)
        row["avoided_critical_pct"] = round(100 * avoided_critical, 1)
        row["score"] = round(SCORE_WEIGHTS["unserved"] * avoided_unserved
                             + SCORE_WEIGHTS["critical"] * avoided_critical
                             + SCORE_WEIGHTS["cost"] * (1 - row["cost"] / max_cost), 1)
    feasible = sorted((r for r in rows if r["feasible"]), key=lambda r: -r["score"])
    for i, row in enumerate(feasible, 1):
        row["rank"] = i
    return feasible + [r for r in rows if not r["feasible"]]


def explain(network: Network, scenario: Scenario, baseline: SimulationResult,
            ranked: list[dict]) -> str:
    """Template explanation citing ledger event ids; no generated facts."""
    ledger = baseline.ledger
    hazard = [e for e in ledger if e["type"] == "hazard"]
    lines = [f"Hour 0: {', '.join(e['asset_name'] for e in hazard)} failed due to "
             f"{scenario.hazard} (events {', '.join(str(e['id']) for e in hazard)})."]
    for e in [e for e in ledger if e["type"] == "state" and e["to"] == FAILED][:4]:
        lines.append(f"Hour {e['t']}: {e['asset_name']} failed - {e['cause']}, "
                     f"{e['rule']} (event {e['id']}).")
    backups = [e for e in ledger if e["to"] == ON_BACKUP]
    if backups:
        lines.append(f"{len(backups)} asset(s) ran on backup power before either recovering "
                     f"or failing (events {', '.join(str(e['id']) for e in backups)}).")
    imp = baseline.impact
    recovery = (f"full recovery at hour {imp['recovery_hour']}" if imp["recovered_within_horizon"]
                else f"no full recovery within the {scenario.horizon_hours}h horizon")
    lines.append(f"Baseline impact: {imp['total_unserved_service_person_hours']:,} unserved "
                 f"service person-hours, {imp['critical_facility_outage_hours']} critical-facility "
                 f"outage hours, {recovery}.")
    best = ranked[0]
    if best["kind"] == "baseline":
        lines.append("No tested intervention improved on the baseline under the scoring weights.")
    else:
        lines.append(f"Best option: {best['label']} - avoids {best['avoided_unserved_pct']}% of "
                     f"unserved service-hours and {best['avoided_critical_pct']}% of critical "
                     f"outage hours at cost {best['cost']:,} (score {best['score']}).")
    lines.append("Model-based estimate on synthetic data; planner review required.")
    return " ".join(lines)
