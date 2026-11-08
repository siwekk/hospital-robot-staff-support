from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

import networkx as nx
import pandas as pd

RAW = Path("data/raw/freiburg_logistics")
MIMIC = Path("data/processed/mimic_parameters.json")
OUTPUT = Path("data/processed/combined_parameters.json")

EXPECTED_MD5 = {
    "Network.graphml": "f698f4f1e86b1e9658e2a74084fb867e",
    "Orders.csv": "606fd8d22adc47ff2866c21618b2d1bd",
    "README.md": "7c276a42ed3bb8fd131ca4485746d5d4",
}


def digest(path: Path, algorithm: str) -> str:
    checksum = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def validate_downloads() -> None:
    for name, expected in EXPECTED_MD5.items():
        actual = digest(RAW / name, "md5")
        if actual != expected:
            raise ValueError(f"Checksum mismatch for {name}: {actual} != {expected}")


def route_record(graph: nx.DiGraph, origin: str, destination: str) -> dict[str, object]:
    path = nx.shortest_path(graph, origin, destination, weight="distance")
    distance = sum(
        float(graph.edges[left, right].get("distance", 0.0))
        for left, right in pairwise(path)
    )
    elevator_rides = 0
    elevator_floors = 0
    previous_was_elevator = False
    for left, right in pairwise(path):
        is_elevator = graph.edges[left, right].get("path_type") == "ELEVATOR"
        if is_elevator:
            if not previous_was_elevator:
                elevator_rides += 1
            left_level = int(graph.nodes[left].get("level", 0))
            right_level = int(graph.nodes[right].get("level", left_level))
            elevator_floors += max(1, abs(right_level - left_level))
        previous_was_elevator = is_elevator
    return {
        "origin": origin,
        "destination": destination,
        "distance_m": float(distance),
        "elevator_rides": int(elevator_rides),
        "elevator_floors": int(elevator_floors),
    }


def main() -> None:
    validate_downloads()
    with MIMIC.open(encoding="utf-8") as handle:
        parameters = json.load(handle)

    orders = pd.read_csv(
        RAW / "Orders.csv",
        dtype={"start_node_id": str, "end_node_id": str},
    )
    timestamps = pd.to_datetime(orders["datetime"], utc=True)
    local_hours = orders["datetime"].str.slice(11, 13).astype(int)
    graph = nx.read_graphml(RAW / "Network.graphml")
    for _, _, attributes in graph.edges(data=True):
        attributes.setdefault("distance", 0.0)

    pair_counts = (
        orders.groupby(["start_node_id", "end_node_id"], sort=True)
        .size()
        .rename("count")
        .reset_index()
    )
    routes: dict[tuple[str, str], dict[str, object]] = {}
    for row in pair_counts.itertuples(index=False):
        key = (row.start_node_id, row.end_node_id)
        routes[key] = route_record(graph, *key)

    by_hour: dict[int, dict[tuple[str, str], int]] = defaultdict(lambda: defaultdict(int))
    for hour, origin, destination in zip(
        local_hours,
        orders["start_node_id"],
        orders["end_node_id"],
        strict=True,
    ):
        by_hour[int(hour)][(origin, destination)] += 1

    empirical_hours: dict[str, dict[str, object]] = {}
    for hour in range(24):
        cumulative = 0
        entries = []
        cumulative_counts = []
        for key, count in sorted(by_hour[hour].items()):
            cumulative += count
            route = routes[key]
            entries.append(
                [
                    route["origin"],
                    route["destination"],
                    route["distance_m"],
                    route["elevator_rides"],
                    route["elevator_floors"],
                ]
            )
            cumulative_counts.append(cumulative)
        empirical_hours[str(hour)] = {
            "total": cumulative,
            "entries": entries,
            "cumulative_counts": cumulative_counts,
        }

    hour_counts = local_hours.value_counts().reindex(range(24), fill_value=0).astype(float)
    hour_weights = hour_counts / hour_counts.sum()
    observation_hours = (timestamps.max() - timestamps.min()).total_seconds() / 3600.0
    weighted_distance = sum(
        int(row.count) * float(routes[(row.start_node_id, row.end_node_id)]["distance_m"])
        for row in pair_counts.itertuples(index=False)
    ) / len(orders)

    parameters["arrival_hour_weights"] = [float(hour_weights.loc[hour]) for hour in range(24)]
    parameters["observed_requests_per_hour"] = float(len(orders) / observation_hours)
    parameters["freiburg"] = {
        "dataset_doi": "https://doi.org/10.5281/zenodo.19085901",
        "network_nodes": graph.number_of_nodes(),
        "network_edges": graph.number_of_edges(),
        "weak_components": nx.number_weakly_connected_components(graph),
        "orders": len(orders),
        "unique_origins": int(orders["start_node_id"].nunique()),
        "unique_destinations": int(orders["end_node_id"].nunique()),
        "unique_od_pairs": len(pair_counts),
        "first_request_utc": timestamps.min().isoformat(),
        "last_request_utc": timestamps.max().isoformat(),
        "mean_shortest_route_m": float(weighted_distance),
        "file_md5": EXPECTED_MD5,
        "file_sha256": {
            name: digest(RAW / name, "sha256") for name in EXPECTED_MD5
        },
    }
    parameters["empirical_routes_by_hour"] = empirical_hours
    parameters["pathway_network"] = {
        "nodes": [
            [str(node), int(attributes.get("level", 0))]
            for node, attributes in graph.nodes(data=True)
        ],
        "edges": [
            [str(origin), str(destination), float(attributes.get("distance", 0.0)),
             attributes.get("path_type", "PATH")]
            for origin, destination, attributes in graph.edges(data=True)
        ],
    }
    daily_requests: dict[str, list[list[object]]] = defaultdict(list)
    for timestamp, origin, destination in zip(
        orders["datetime"],
        orders["start_node_id"],
        orders["end_node_id"],
        strict=True,
    ):
        minute = int(timestamp[11:13]) * 60 + int(timestamp[14:16])
        daily_requests[timestamp[:10]].append([minute, origin, destination])
    parameters["empirical_daily_requests"] = [
        {
            "date": date,
            "requests": sorted(requests, key=lambda item: (item[0], item[1], item[2])),
        }
        for date, requests in sorted(daily_requests.items())
    ]
    parameters["synthetic_mapping_notice"] = (
        "Freiburg supplies observed request times, origins, destinations, and routes. "
        "MIMIC supplies clinical task mix and urgency assumptions because the Freiburg "
        "release does not identify the clinical contents of individual orders."
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(parameters, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(
        f"Wrote {OUTPUT}: {len(orders)} orders, {len(pair_counts)} OD pairs, "
        f"{weighted_distance:.1f} m mean shortest route"
    )


if __name__ == "__main__":
    main()
