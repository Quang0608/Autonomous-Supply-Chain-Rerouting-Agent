"""Small synthetic service network over named real ports for a pilot only.

Connections, service availability, costs and transit times are NOT verified
commercial services. Replace this module with sourced lane data in Phase 2.
"""
from __future__ import annotations

from collections import defaultdict
import heapq
import math

# Country -> (UN/LOCODE-like code, port name, hub region).
# This is a convenience mapping, NOT verified factory-to-port location evidence.
COUNTRY_PORT = {
    "Japan": ("JPYOK", "Yokohama", "asia"),
    "China": ("CNSHA", "Shanghai", "asia"),
    "South Korea": ("KRPUS", "Busan", "asia"),
    "Republic of Korea": ("KRPUS", "Busan", "asia"),
    "Singapore": ("SGSIN", "Singapore", "asia"),
    "Vietnam": ("VNSGN", "Ho Chi Minh City", "asia"),
    "Thailand": ("THLCH", "Laem Chabang", "asia"),
    "India": ("INNSA", "Nhava Sheva", "asia"),
    "Malaysia": ("MYPKG", "Port Klang", "asia"),
    "United Arab Emirates": ("AEJEA", "Jebel Ali", "middle_east"),
    "Australia": ("AUMEL", "Melbourne", "oceania"),
    "South Africa": ("ZADUR", "Durban", "africa"),
    "Argentina": ("ARBUE", "Buenos Aires", "south_america"),
    "Brazil": ("BRSSZ", "Santos", "south_america"),
    "Germany": ("DEHAM", "Hamburg", "europe"),
    "Denmark": ("DKAAR", "Aarhus", "europe"),
    "Netherlands": ("NLRTM", "Rotterdam", "europe"),
    "France": ("FRLEH", "Le Havre", "europe"),
    "United Kingdom": ("GBSOU", "Southampton", "europe"),
    "Belgium": ("BEANR", "Antwerp", "europe"),
    "Italy": ("ITGOA", "Genoa", "europe"),
    "Spain": ("ESVLC", "Valencia", "europe"),
    "Sweden": ("SEGOT", "Gothenburg", "europe"),
    "Norway": ("NOOSL", "Oslo", "europe"),
    "United States": ("USNYC", "New York", "north_america"),
    "United States of America": ("USNYC", "New York", "north_america"),
    "Canada": ("USNYC", "New York (modeled gateway)", "north_america"),
    "Mexico": ("USNYC", "New York (modeled gateway)", "north_america"),
}
HUBS = {"SGSIN", "AEJEA", "NLRTM", "ZADUR", "ARBUE", "USNYC"}
REGION_HUBS = {
    "asia": ("SGSIN", "AEJEA"), "middle_east": ("AEJEA", "SGSIN"),
    "oceania": ("SGSIN", "ZADUR"), "africa": ("ZADUR", "AEJEA"),
    "south_america": ("ARBUE", "USNYC"), "europe": ("NLRTM", "AEJEA"),
    "north_america": ("USNYC", "NLRTM"),
}
# Modeled transit-time edges; not actual shipping schedules.
HUB_LINKS = [
    ("SGSIN", "AEJEA", 10), ("AEJEA", "NLRTM", 16),
    ("SGSIN", "NLRTM", 26), ("SGSIN", "ZADUR", 13),
    ("ZADUR", "NLRTM", 17), ("ZADUR", "ARBUE", 12),
    ("ARBUE", "USNYC", 12), ("USNYC", "NLRTM", 12),
    ("USNYC", "SGSIN", 28), ("ARBUE", "NLRTM", 17),
    ("ZADUR", "AEJEA", 12), ("AEJEA", "USNYC", 29)
]


def build_network():
    ports = {v[0]: {"id": v[0], "name": v[1], "source_class": "REAL_PORT_NAME__GATEWAY_MODELED"}
             for v in COUNTRY_PORT.values()}
    edges = {}
    def add(a, b, days):
        if a == b:
            return
        for start, end in ((a,b), (b,a)):
            edges[(start,end)] = {"from":start,"to":end,"transit_days":days,
                                  "cost_units":int(days*100),"source_class":"SYNTHETIC_SERVICE"}
    for a,b,d in HUB_LINKS:
        add(a,b,d)
    for port, _, region in COUNTRY_PORT.values():
        if port not in HUBS:
            for hub in REGION_HUBS[region]:
                add(port,hub,6)
    return ports, edges


def shortest_path(origin: str, destination: str, edges: dict, blocked: set[str] | None = None):
    blocked = blocked or set()
    if origin in blocked or destination in blocked:
        return None
    adjacency = defaultdict(list)
    for (a,b), data in edges.items():
        if a not in blocked and b not in blocked:
            adjacency[a].append((b,data["transit_days"]))
    frontier = [(0.0, (origin,))]
    best = {}
    while frontier:
        time, path = heapq.heappop(frontier)
        curr = path[-1]
        if curr in best and best[curr] <= time:
            continue
        best[curr] = time
        if curr == destination:
            return {"ports":list(path),"transit_days":time,
                    "cost_units":sum(edges[(a,b)]["cost_units"]
                                     for a,b in zip(path,path[1:]))}
        for nxt, days in adjacency[curr]:
            if nxt not in path:
                heapq.heappush(frontier, (time+days,path+(nxt,)))
    return None
