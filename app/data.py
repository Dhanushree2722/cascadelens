"""Synthetic demo city. All values are illustrative, not real infrastructure data."""

import networkx as nx

from app.simulator import Asset, Edge, Network

# id, name, type, service, capacity, people_served, backup_hours, repair_hours, x, y
_ASSETS = [
    ("S1", "North Substation", "substation", "power", 100, 0, 0, 24, 150, 70),
    ("S2", "South Substation", "substation", "power", 100, 0, 0, 24, 450, 70),
    ("S3", "East Substation", "substation", "power", 120, 0, 0, 24, 750, 70),
    ("P1", "North Pump Station", "pump", "water", 30, 0, 0, 12, 150, 170),
    ("P2", "South Pump Station", "pump", "water", 30, 0, 0, 12, 450, 170),
    ("W1", "Water Treatment Plant", "treatment", "water", 60, 0, 2, 36, 750, 170),
    ("T1", "North Telecom Tower", "telecom", "telecom", 0, 15000, 4, 8, 60, 280),
    ("H1", "City Hospital", "hospital", "healthcare", 0, 400, 8, 24, 200, 280),
    ("T2", "South Telecom Tower", "telecom", "telecom", 0, 15000, 4, 8, 380, 280),
    ("H2", "South Clinic", "hospital", "healthcare", 0, 150, 12, 24, 520, 280),
    ("C1", "Emergency Ops Center", "eoc", "coordination", 0, 60, 24, 24, 640, 280),
    ("T3", "East Telecom Tower", "telecom", "telecom", 0, 12000, 6, 8, 800, 280),
    ("SH1", "North Shelter", "shelter", "shelter", 0, 800, 0, 12, 150, 390),
    ("SH2", "East Shelter", "shelter", "shelter", 0, 600, 0, 12, 750, 390),
    ("R1", "Northgate Feeder", "residential", "residential", 0, 9000, 0, 12, 60, 490),
    ("R2", "Riverside Feeder", "residential", "residential", 0, 8000, 0, 12, 200, 490),
    ("R3", "Southpark Feeder", "residential", "residential", 0, 9000, 0, 12, 380, 490),
    ("R4", "Harbor Feeder", "residential", "residential", 0, 7000, 0, 12, 520, 490),
    ("R5", "Eastfield Feeder", "residential", "residential", 0, 8000, 0, 12, 700, 490),
    ("R6", "Hillcrest Feeder", "residential", "residential", 0, 6000, 0, 12, 840, 490),
]

# supplier -> dependent, load drawn from the supplier, active
_EDGES = [
    ("S1", "P1", 20), ("S1", "T1", 5), ("S1", "H1", 30), ("S1", "SH1", 10),
    ("S1", "R1", 20), ("S1", "R2", 15),
    ("S2", "P2", 20), ("S2", "T2", 5), ("S2", "H2", 15), ("S2", "C1", 10),
    ("S2", "R3", 25), ("S2", "R4", 20),
    ("S3", "W1", 30), ("S3", "T3", 5), ("S3", "SH2", 10), ("S3", "R5", 25), ("S3", "R6", 20),
    ("W1", "P1", 15), ("W1", "P2", 15),
    ("P1", "H1", 10), ("P1", "SH1", 5), ("P1", "R1", 5), ("P1", "R2", 5),
    ("P2", "H2", 5), ("P2", "SH2", 5), ("P2", "R3", 5), ("P2", "R4", 5),
    ("T2", "C1", 1),
]

# Alternate connections that exist physically but are switched off by default.
_ALTERNATES = [
    ("ALT-S2-H1", "S2", "H1", 30),
    ("ALT-S3-P1", "S3", "P1", 20),
    ("ALT-S3-T1", "S3", "T1", 5),
]


def build_network() -> Network:
    assets = {row[0]: Asset(*row) for row in _ASSETS}
    edges = {}
    for supplier, dependent, load in _EDGES:
        edge_id = f"{supplier}-{dependent}"
        edges[edge_id] = Edge(edge_id, supplier, dependent, load, True)
    for edge_id, supplier, dependent, load in _ALTERNATES:
        edges[edge_id] = Edge(edge_id, supplier, dependent, load, False)
    graph = nx.DiGraph()
    graph.add_nodes_from(assets)
    graph.add_edges_from((e.supplier, e.dependent) for e in edges.values())
    return Network(assets=assets, edges=edges, graph=graph)
