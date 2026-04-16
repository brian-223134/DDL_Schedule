#!/usr/bin/env python3
"""Split MySQL migration SQL into canary-safe execution phases.

This script reads a forward migration (and optional rollback migration),
splits SQL into statement-level units, classifies each statement into one
execution phase, and emits phase files + unit files + a manifest.

Phases:
- pre: additive schema changes that should be safe before rollout
- data: data backfill / cleanup statements
- post: contractive or strict constraints that require old code shutdown
- manual: ambiguous or mixed statements that require human review
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

PHASE_ORDER = ("pre", "data", "post", "manual")


@dataclass
class Unit:
    source_order: int
    phase: str
    reason: str
    sql: str
    summary: str
    unit_id: str = ""


def split_sql_statements(sql_text: str) -> list[str]:
    """Split SQL text into statements by semicolon outside literals/comments."""
    statements: list[str] = []
    buf: list[str] = []

    in_single = False
    in_double = False
    in_backtick = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    length = len(sql_text)
    while i < length:
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < length else ""

        if in_line_comment:
            buf.append(ch)
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            buf.append(ch)
            if ch == "*" and nxt == "/":
                buf.append(nxt)
                i += 2
                in_block_comment = False
                continue
            i += 1
            continue

        if in_single:
            buf.append(ch)
            if ch == "\\" and nxt:
                buf.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            buf.append(ch)
            if ch == "\\" and nxt:
                buf.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        if in_backtick:
            buf.append(ch)
            if ch == "`":
                in_backtick = False
            i += 1
            continue

        # comment start detection
        if ch == "-" and nxt == "-":
            third = sql_text[i + 2] if i + 2 < length else ""
            if third == "" or third.isspace():
                buf.extend((ch, nxt))
                i += 2
                in_line_comment = True
                continue

        if ch == "#":
            buf.append(ch)
            i += 1
            in_line_comment = True
            continue

        if ch == "/" and nxt == "*":
            buf.extend((ch, nxt))
            i += 2
            in_block_comment = True
            continue

        if ch == "'":
            buf.append(ch)
            in_single = True
            i += 1
            continue

        if ch == '"':
            buf.append(ch)
            in_double = True
            i += 1
            continue

        if ch == "`":
            buf.append(ch)
            in_backtick = True
            i += 1
            continue

        if ch == ";":
            buf.append(ch)
            statement = "".join(buf).strip()
            if statement:
                statements.append(statement)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)

    return statements


def strip_comments(sql: str) -> str:
    """Remove comments for classification while preserving literals."""
    out: list[str] = []

    in_single = False
    in_double = False
    in_backtick = False
    in_line_comment = False
    in_block_comment = False

    i = 0
    length = len(sql)
    while i < length:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < length else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
                out.append(ch)
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                i += 2
                in_block_comment = False
                continue
            i += 1
            continue

        if in_single:
            out.append(ch)
            if ch == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if ch == "'":
                in_single = False
            i += 1
            continue

        if in_double:
            out.append(ch)
            if ch == "\\" and nxt:
                out.append(nxt)
                i += 2
                continue
            if ch == '"':
                in_double = False
            i += 1
            continue

        if in_backtick:
            out.append(ch)
            if ch == "`":
                in_backtick = False
            i += 1
            continue

        if ch == "-" and nxt == "-":
            third = sql[i + 2] if i + 2 < length else ""
            if third == "" or third.isspace():
                in_line_comment = True
                i += 2
                continue

        if ch == "#":
            in_line_comment = True
            i += 1
            continue

        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue

        if ch == "'":
            out.append(ch)
            in_single = True
            i += 1
            continue

        if ch == '"':
            out.append(ch)
            in_double = True
            i += 1
            continue

        if ch == "`":
            out.append(ch)
            in_backtick = True
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)


def normalize_for_match(sql: str) -> str:
    cleaned = strip_comments(sql)
    return re.sub(r"\s+", " ", cleaned).strip().upper()


def summarize(sql: str, max_len: int = 140) -> str:
    normalized = normalize_for_match(sql)
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3] + "..."


def classify_statement(sql: str) -> tuple[str, str]:
    text = normalize_for_match(sql)
    if not text:
        return "manual", "Only comments or empty SQL"

    # Session / transaction controls (kept as pre by default)
    if text.startswith(("SET ", "USE ", "START TRANSACTION", "COMMIT", "ROLLBACK")):
        return "pre", "Session or transaction control statement"

    if text.startswith("CREATE TABLE"):
        return "pre", "CREATE TABLE is typically additive"

    if text.startswith("DROP TABLE"):
        return "post", "DROP TABLE is a contract/destructive change"

    if text.startswith(("INSERT ", "REPLACE ")):
        return "data", "INSERT/REPLACE is data migration"

    if text.startswith(("UPDATE ", "DELETE ", "LOAD DATA ")):
        return "data", "UPDATE/DELETE/LOAD DATA is data migration"

    if text.startswith("CREATE UNIQUE INDEX"):
        return "post", "UNIQUE index can reject old or duplicate writes"

    if text.startswith("CREATE INDEX"):
        return "pre", "Non-unique index addition is additive"

    if text.startswith("DROP INDEX"):
        return "post", "DROP INDEX can regress old query performance"

    if text.startswith("TRUNCATE TABLE"):
        return "post", "TRUNCATE is destructive"

    if text.startswith("RENAME TABLE"):
        return "manual", "RENAME TABLE is risky in blue/green; use expand-contract"

    if text.startswith("ALTER TABLE"):
        return classify_alter_table(text)

    if text.startswith(("CREATE TRIGGER", "DROP TRIGGER")):
        return "manual", "Trigger changes can affect old and new write paths"

    return "manual", "Unknown statement type; requires review"


def classify_alter_table(text: str) -> tuple[str, str]:
    phases: set[str] = set()
    reasons: list[str] = []
    manual_reasons: list[str] = []

    def mark(phase: str, reason: str, cond: bool) -> None:
        if cond:
            phases.add(phase)
            reasons.append(reason)

    mark("post", "DROP COLUMN is contract change", bool(re.search(r"\bDROP\s+COLUMN\b", text)))
    mark(
        "post",
        "DROP INDEX/KEY can hurt old query paths",
        bool(re.search(r"\bDROP\s+(INDEX|KEY|PRIMARY\s+KEY)\b", text)),
    )
    mark(
        "post",
        "DROP FOREIGN KEY changes relational contract",
        bool(re.search(r"\bDROP\s+FOREIGN\s+KEY\b", text)),
    )
    mark(
        "post",
        "DROP CONSTRAINT changes table contract",
        bool(re.search(r"\bDROP\s+CONSTRAINT\b", text)),
    )
    mark(
        "post",
        "ADD FOREIGN KEY enforces new write constraints",
        bool(re.search(r"\bADD\s+(CONSTRAINT\s+[^\s]+\s+)?FOREIGN\s+KEY\b", text)),
    )
    mark(
        "post",
        "ADD CHECK enforces new write constraints",
        bool(re.search(r"\bADD\s+(CONSTRAINT\s+[^\s]+\s+)?CHECK\b", text)),
    )
    mark(
        "post",
        "ADD UNIQUE may reject existing/old writes",
        bool(
            re.search(
                r"\bADD\s+(UNIQUE\b|UNIQUE\s+(INDEX|KEY)\b|CONSTRAINT\s+[^\s]+\s+UNIQUE\b)",
                text,
            )
        ),
    )

    has_add_column = bool(re.search(r"\bADD\s+COLUMN\b", text))
    if has_add_column:
        has_not_null = bool(re.search(r"\bADD\s+COLUMN\b[^;]*\bNOT\s+NULL\b", text))
        has_default = bool(re.search(r"\bADD\s+COLUMN\b[^;]*\bDEFAULT\b", text))
        if has_not_null and not has_default:
            mark(
                "post",
                "ADD COLUMN NOT NULL without DEFAULT can break old inserts",
                True,
            )
        else:
            mark("pre", "ADD COLUMN nullable/default is additive", True)

    has_add_index = bool(re.search(r"\bADD\s+(INDEX|KEY)\b", text))
    has_add_unique_index = bool(re.search(r"\bADD\s+UNIQUE\s+(INDEX|KEY)\b", text))
    if has_add_index and not has_add_unique_index:
        mark("pre", "ADD INDEX is additive", True)

    mark(
        "post",
        "MODIFY/CHANGE to NOT NULL tightens constraints",
        bool(re.search(r"\b(MODIFY|CHANGE)\b[^;]*\bNOT\s+NULL\b", text)),
    )
    mark(
        "post",
        "SET NOT NULL tightens constraints",
        bool(re.search(r"\bALTER\s+COLUMN\b[^;]*\bSET\s+NOT\s+NULL\b", text)),
    )

    if re.search(r"\bRENAME\s+(COLUMN|TO)\b", text):
        manual_reasons.append("RENAME in ALTER TABLE needs expand-contract pattern")

    if re.search(r"\b(MODIFY|CHANGE)\b[^;]*\bENUM\s*\(", text):
        manual_reasons.append("ENUM MODIFY/CHANGE needs manual check for expand vs shrink")

    if re.search(r"\b(ALTER\s+COLUMN\b[^;]*\b(SET|DROP)\s+DEFAULT|DROP\s+DEFAULT\b)", text):
        manual_reasons.append("DEFAULT behavior change is conditional")

    if re.search(r"\b(MODIFY|CHANGE)\b", text) and not re.search(
        r"\b(MODIFY|CHANGE)\b[^;]*\bNOT\s+NULL\b", text
    ):
        manual_reasons.append("Column type/shape change is conditional")

    if manual_reasons and phases:
        details = "; ".join(sorted(set(manual_reasons)))
        return "manual", f"Mixed automatic phase + conditional rules: {details}"

    if manual_reasons and not phases:
        return "manual", "; ".join(sorted(set(manual_reasons)))

    if not phases:
        return "manual", "Unknown ALTER TABLE pattern; requires review"

    if len(phases) > 1:
        return (
            "manual",
            "ALTER TABLE includes mixed phase actions; split into separate statements",
        )

    phase = next(iter(phases))
    return phase, "; ".join(sorted(set(reasons)))


def ensure_statement_terminator(sql: str) -> str:
    text = sql.strip()
    if not text:
        return text
    if text.endswith(";"):
        return text
    return text + ";"


def assign_ids(units: Iterable[Unit]) -> None:
    counters: Counter[str] = Counter()
    for unit in units:
        counters[unit.phase] += 1
        unit.unit_id = f"{unit.phase}-{counters[unit.phase]:03d}"


def group_filename(base: str, phase: str, rollback: bool) -> str:
    if rollback:
        return f"{base}.{phase}.rollback.sql"
    return f"{base}.{phase}.sql"


def unit_filename(base: str, phase: str, idx: int, rollback: bool) -> str:
    if rollback:
        return f"{base}.{phase}.rollback.{idx:03d}.sql"
    return f"{base}.{phase}.{idx:03d}.sql"


def parse_sql_file(source_file: Path) -> list[Unit]:
    raw = source_file.read_text(encoding="utf-8")
    statements = split_sql_statements(raw)

    units: list[Unit] = []
    for i, statement in enumerate(statements, start=1):
        phase, reason = classify_statement(statement)
        units.append(
            Unit(
                source_order=i,
                phase=phase,
                reason=reason,
                sql=statement,
                summary=summarize(statement),
            )
        )
    return units


def extract_alter_enum_signature(sql: str) -> tuple[str, str, tuple[str, ...]] | None:
    text = normalize_for_match(sql)
    pattern = re.compile(
        r"^ALTER TABLE\s+`?([A-Z0-9_]+)`?\s+(?:MODIFY|CHANGE)\s+COLUMN\s+`?([A-Z0-9_]+)`?\s+ENUM\s*\((.*?)\)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None

    table, column, values_blob = match.groups()
    values = tuple(re.findall(r"'((?:''|[^'])*)'", values_blob))
    if not values:
        return None
    return table.upper(), column.upper(), values


def infer_enum_phase_from_pair(forward_units: list[Unit], rollback_units: list[Unit]) -> None:
    forward_map: dict[tuple[str, str], Unit] = {}
    rollback_map: dict[tuple[str, str], Unit] = {}

    for unit in forward_units:
        sig = extract_alter_enum_signature(unit.sql)
        if not sig:
            continue
        key = (sig[0], sig[1])
        if key not in forward_map:
            forward_map[key] = unit

    for unit in rollback_units:
        sig = extract_alter_enum_signature(unit.sql)
        if not sig:
            continue
        key = (sig[0], sig[1])
        if key not in rollback_map:
            rollback_map[key] = unit

    for key in set(forward_map).intersection(rollback_map):
        f_unit = forward_map[key]
        r_unit = rollback_map[key]
        f_sig = extract_alter_enum_signature(f_unit.sql)
        r_sig = extract_alter_enum_signature(r_unit.sql)
        if not f_sig or not r_sig:
            continue

        f_values = set(f_sig[2])
        r_values = set(r_sig[2])
        if f_values == r_values:
            continue

        if f_values.issuperset(r_values):
            f_unit.phase = "pre"
            f_unit.reason = "ENUM expansion inferred from forward/rollback pair"
            r_unit.phase = "post"
            r_unit.reason = "ENUM shrink inferred from forward/rollback pair"
            continue

        if f_values.issubset(r_values):
            f_unit.phase = "post"
            f_unit.reason = "ENUM shrink inferred from forward/rollback pair"
            r_unit.phase = "pre"
            r_unit.reason = "ENUM expansion inferred from forward/rollback pair"


def write_sql_artifacts(
    source_file: Path,
    out_dir: Path,
    base_name: str,
    rollback: bool,
    units: list[Unit],
) -> dict:
    assign_ids(units)

    phase_groups: dict[str, list[Unit]] = {phase: [] for phase in PHASE_ORDER}
    for unit in units:
        phase_groups[unit.phase].append(unit)

    generated_files: list[str] = []

    for phase in PHASE_ORDER:
        current = phase_groups[phase]
        if not current:
            continue

        phase_path = out_dir / group_filename(base_name, phase, rollback)
        lines: list[str] = [
            "-- Auto-generated by migration_phase_splitter.py",
            f"-- source: {source_file}",
            f"-- phase: {phase}",
            f"-- generated_at_utc: {datetime.now(timezone.utc).isoformat()}",
            "",
        ]

        for unit in current:
            lines.extend(
                [
                    f"-- unit: {unit.unit_id}",
                    f"-- source_order: {unit.source_order}",
                    f"-- reason: {unit.reason}",
                    ensure_statement_terminator(unit.sql),
                    "",
                ]
            )

        phase_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        generated_files.append(str(phase_path))

        for idx, unit in enumerate(current, start=1):
            unit_path = out_dir / unit_filename(base_name, phase, idx, rollback)
            unit_lines = [
                "-- Auto-generated statement unit",
                f"-- source: {source_file}",
                f"-- unit: {unit.unit_id}",
                f"-- source_order: {unit.source_order}",
                f"-- reason: {unit.reason}",
                "",
                ensure_statement_terminator(unit.sql),
                "",
            ]
            unit_path.write_text("\n".join(unit_lines), encoding="utf-8")
            generated_files.append(str(unit_path))

    phase_counts = {phase: len(phase_groups[phase]) for phase in PHASE_ORDER}

    return {
        "source_file": str(source_file),
        "kind": "rollback" if rollback else "forward",
        "total_statements": len(units),
        "phase_counts": phase_counts,
        "needs_manual_review": phase_counts["manual"] > 0,
        "units": [
            {
                "id": unit.unit_id,
                "phase": unit.phase,
                "source_order": unit.source_order,
                "reason": unit.reason,
                "summary": unit.summary,
            }
            for unit in units
        ],
        "generated_files": generated_files,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split SQL migration into canary-safe phase files and unit files."
    )
    parser.add_argument("--forward", required=True, help="Path to forward migration SQL")
    parser.add_argument(
        "--rollback",
        default=None,
        help="Path to rollback migration SQL (optional)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory (default: <forward_dir>/split_migrations)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with non-zero code when manual-review statements exist",
    )

    args = parser.parse_args()

    forward_path = Path(args.forward).expanduser().resolve()
    if not forward_path.exists():
        print(f"[error] forward migration not found: {forward_path}", file=sys.stderr)
        return 1

    rollback_path: Path | None = None
    if args.rollback:
        rollback_path = Path(args.rollback).expanduser().resolve()
        if not rollback_path.exists():
            print(f"[error] rollback migration not found: {rollback_path}", file=sys.stderr)
            return 1

    out_dir = (
        Path(args.out_dir).expanduser().resolve()
        if args.out_dir
        else forward_path.parent / "split_migrations"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    base_name = forward_path.name
    if base_name.endswith(".sql"):
        base_name = base_name[: -len(".sql")]

    forward_units = parse_sql_file(forward_path)
    rollback_units: list[Unit] | None = None
    if rollback_path is not None:
        rollback_units = parse_sql_file(rollback_path)
        infer_enum_phase_from_pair(forward_units, rollback_units)

    forward_result = write_sql_artifacts(
        source_file=forward_path,
        out_dir=out_dir,
        base_name=base_name,
        rollback=False,
        units=forward_units,
    )

    rollback_result: dict | None = None
    if rollback_path is not None and rollback_units is not None:
        rollback_result = write_sql_artifacts(
            source_file=rollback_path,
            out_dir=out_dir,
            base_name=base_name,
            rollback=True,
            units=rollback_units,
        )

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "out_dir": str(out_dir),
        "forward": forward_result,
        "rollback": rollback_result,
        "notes": [
            "manual phase statements require human review before automation",
            "mixed pre/post operations in one ALTER TABLE are emitted as manual",
        ],
    }

    manifest_path = out_dir / f"{base_name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[ok] output directory: {out_dir}")
    print(f"[ok] manifest: {manifest_path}")
    print("[ok] forward phase counts:", forward_result["phase_counts"])
    if rollback_result:
        print("[ok] rollback phase counts:", rollback_result["phase_counts"])

    has_manual = forward_result["needs_manual_review"] or (
        rollback_result["needs_manual_review"] if rollback_result else False
    )
    if args.strict and has_manual:
        print("[error] manual-review statements found (strict mode)", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
