#!/usr/bin/env python3
"""Assign GTFS stops to BFS municipalities using a grid-indexed PIP join."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

GRID_SIZE = 0.05


def ring_bbox(ring: list[list[float]]) -> tuple[float, float, float, float]:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    for index, (x2, y2) in enumerate(ring):
        x1, y1 = ring[index - 1]
        if (y1 > y) != (y2 > y):
            crossing_x = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing_x:
                inside = not inside
    return inside


def point_in_polygon(x: float, y: float, polygon: list[list[list[float]]]) -> bool:
    if not point_in_ring(x, y, polygon[0]):
        return False
    return not any(point_in_ring(x, y, hole) for hole in polygon[1:])


def point_in_geometry(x: float, y: float, geometry: dict[str, Any]) -> bool:
    if geometry["type"] == "Polygon":
        return point_in_polygon(x, y, geometry["coordinates"])
    if geometry["type"] == "MultiPolygon":
        return any(
            point_in_polygon(x, y, polygon) for polygon in geometry["coordinates"]
        )
    return False


def geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    rings = (
        geometry["coordinates"]
        if geometry["type"] == "Polygon"
        else [ring for polygon in geometry["coordinates"] for ring in polygon]
    )
    boxes = [ring_bbox(ring) for ring in rings]
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def grid_cell(value: float) -> int:
    return math.floor(value / GRID_SIZE)


def load_municipalities(
    path: Path,
) -> tuple[list[dict[str, Any]], dict[tuple[int, int], list[int]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    municipalities: list[dict[str, Any]] = []
    grid: dict[tuple[int, int], list[int]] = {}
    for feature in data["features"]:
        properties = feature.get("properties", {})
        geometry = feature.get("geometry")
        if not geometry or geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            continue
        municipality = {
            "gdenr": str(properties.get("GDENR", "")),
            "gdename": str(properties.get("GDENAME", "")),
            "geometry": geometry,
        }
        index = len(municipalities)
        municipalities.append(municipality)
        xmin, ymin, xmax, ymax = geometry_bbox(geometry)
        for gx in range(grid_cell(xmin), grid_cell(xmax) + 1):
            for gy in range(grid_cell(ymin), grid_cell(ymax) + 1):
                grid.setdefault((gx, gy), []).append(index)
    return municipalities, grid


def assign_municipality(
    lon: float,
    lat: float,
    municipalities: list[dict[str, Any]],
    grid: dict[tuple[int, int], list[int]],
) -> dict[str, str]:
    candidates = grid.get((grid_cell(lon), grid_cell(lat)), [])
    for index in candidates:
        municipality = municipalities[index]
        if point_in_geometry(lon, lat, municipality["geometry"]):
            return {
                "municipality_gdenr": municipality["gdenr"],
                "municipality_name": municipality["gdename"],
            }
    return {"municipality_gdenr": "", "municipality_name": ""}


def join_stops(
    stops_path: Path, boundaries_path: Path, output_path: Path
) -> dict[str, Any]:
    municipalities, grid = load_municipalities(boundaries_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = 0
    assigned = 0
    assigned_counts: Counter[str] = Counter()
    with stops_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as source, output_path.open("w", encoding="utf-8", newline="") as target:
        reader = csv.DictReader(source)
        fields = list(reader.fieldnames or []) + [
            "municipality_gdenr",
            "municipality_name",
        ]
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for row in reader:
            rows += 1
            try:
                lon = float(row.get("stop_lon", ""))
                lat = float(row.get("stop_lat", ""))
                municipality = assign_municipality(lon, lat, municipalities, grid)
            except ValueError:
                municipality = {"municipality_gdenr": "", "municipality_name": ""}
            row.update(municipality)
            if municipality["municipality_gdenr"]:
                assigned += 1
                assigned_counts[municipality["municipality_gdenr"]] += 1
            writer.writerow(row)
    profile = {
        "stops_input": str(stops_path),
        "boundaries_input": str(boundaries_path),
        "municipality_features": len(municipalities),
        "stop_rows": rows,
        "assigned_rows": assigned,
        "unassigned_rows": rows - assigned,
        "assignment_rate": assigned / rows if rows else None,
        "municipalities_with_stops": len(assigned_counts),
        "top_municipalities_by_stop_count": assigned_counts.most_common(20),
    }
    report_path = output_path.with_name("stop_municipality_profile.json")
    report_path.write_text(
        json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stops", type=Path, required=True)
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    profile = join_stops(args.stops, args.boundaries, args.output)
    print(json.dumps(profile, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
