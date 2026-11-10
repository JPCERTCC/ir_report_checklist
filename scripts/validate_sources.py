#!/usr/bin/env python3
"""Validate the canonical checklist Markdown files before tests/build."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable

from build_checklist import BuildError, parse_and_render, validate_source_file


def validate(path: Path) -> tuple[int, int]:
    text = path.read_text(encoding="utf-8-sig")
    validate_source_file(path, text)
    document_id = path.stem.replace(" ", "-")
    _, _, row_count, _ = parse_and_render(text, document_id)
    return row_count


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--customer",
        type=Path,
        default=Path("checklist_for_customer.md"),
    )
    parser.add_argument(
        "--reporter",
        type=Path,
        default=Path("checklist_for_reporter.md"),
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    failed = False
    for label, path in (("customer", args.customer), ("reporter", args.reporter)):
        try:
            rows = validate(path)
        except (BuildError, OSError) as exc:
            print(f"[ERROR] {label}: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"[OK] {label}: {path} (rows={rows})")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
