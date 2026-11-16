#!/usr/bin/env python3
"""Validate the production run contract locally without AWS or network calls."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from src.loaders.municipality_weather import load_weather_points
from src.runs import validate_run_context
from src.storage import build_key


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--execution-id", required=True)
    parser.add_argument("--observation-date", required=True)
    parser.add_argument("--point-snapshot", required=True)
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    if args.batch_size < 1:
        raise ValueError("batch-size must be >= 1")

    points = load_weather_points(args.points)
    batch_count = (len(points) + args.batch_size - 1) // args.batch_size
    event = {
        "source": "municipality_weather",
        "run_id": args.run_id,
        "execution_id": args.execution_id,
        "observation_date": args.observation_date,
        "point_snapshot": args.point_snapshot,
        "batch": 0,
        "batch_size": args.batch_size,
    }
    validate_run_context(event, "municipality_weather")
    observation_datetime = datetime.fromisoformat(args.observation_date).replace(
        tzinfo=timezone.utc
    )
    first_key = build_key(
        "municipality_weather",
        "json",
        now=observation_datetime,
        part=0,
        run_id=args.run_id,
    )
    repeated_key = build_key(
        "municipality_weather",
        "json",
        now=observation_datetime,
        part=0,
        run_id=args.run_id,
    )
    if first_key != repeated_key:
        raise AssertionError("run_id did not produce a deterministic batch key")

    print(
        json.dumps(
            {
                "status": "ok",
                "source": "municipality_weather",
                "municipality_count": len(points),
                "batch_size": args.batch_size,
                "batch_count": batch_count,
                "first_batch_key": first_key,
                "deterministic_key": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
