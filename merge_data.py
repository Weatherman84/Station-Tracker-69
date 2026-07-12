#!/usr/bin/env python3
"""
Deep-merges the just-written local data.json with whatever is currently on
origin/main, so concurrent workflows (fetch, backfill, METAR, Polymarket)
never conflict at the git level. Git can't merge JSON semantically — this
script understands the actual structure (snapshot lists keyed by
capturedAt, plain dicts, etc.) and merges accordingly.

Usage: python merge_data.py <local_file> <remote_file> <output_file>
Called from every workflow's commit step, right before `git add`.
"""
import json
import sys


def merge_snapshot_list(local_list, remote_list):
    # Each entry is a dict with a "capturedAt" timestamp that uniquely
    # identifies it — dedupe by that, keep both sides' entries, sort by time.
    by_key = {}
    for entry in (remote_list or []):
        key = entry.get("capturedAt")
        if key is not None:
            by_key[key] = entry
    for entry in (local_list or []):
        key = entry.get("capturedAt")
        if key is not None:
            by_key[key] = entry  # local wins on exact-timestamp collision (shouldn't happen in practice)
    return sorted(by_key.values(), key=lambda e: e.get("capturedAt", ""))


def merge_metar_list(local_list, remote_list):
    by_key = {}
    for entry in (remote_list or []):
        key = entry.get("obsTime")
        if key is not None:
            by_key[key] = entry
    for entry in (local_list or []):
        key = entry.get("obsTime")
        if key is not None:
            by_key[key] = entry
    return sorted(by_key.values(), key=lambda e: e.get("obsTime", ""))


def deep_merge(local, remote, path=""):
    if local is None:
        return remote
    if remote is None:
        return local

    # forecasts[model][date] and manual[model][date] are snapshot lists
    if path.count("/") >= 3 and path.split("/")[-3] == "forecasts":
        if isinstance(local, list) or isinstance(remote, list):
            return merge_snapshot_list(local if isinstance(local, list) else [],
                                        remote if isinstance(remote, list) else [])

    if path.endswith("/metar") and isinstance(local, list):
        return merge_metar_list(local, remote if isinstance(remote, list) else [])

    if isinstance(local, dict) and isinstance(remote, dict):
        merged = dict(remote)
        for k, v in local.items():
            merged[k] = deep_merge(v, remote.get(k), path=f"{path}/{k}")
        return merged

    # scalars (actuals values, lastUpdated, market blob, etc.) — local (just
    # computed by this run) wins, since it's the freshest write for whatever
    # this specific workflow is responsible for
    return local


def main():
    if len(sys.argv) != 4:
        print("usage: merge_data.py <local_file> <remote_file> <output_file>", file=sys.stderr)
        sys.exit(1)
    local_path, remote_path, out_path = sys.argv[1:4]

    with open(local_path) as f:
        local = json.load(f)

    try:
        with open(remote_path) as f:
            remote = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        remote = {}

    merged = deep_merge(local, remote)

    with open(out_path, "w") as f:
        json.dump(merged, f, indent=1, ensure_ascii=False)
    print(f"merged {local_path} + {remote_path} -> {out_path}")


if __name__ == "__main__":
    main()
