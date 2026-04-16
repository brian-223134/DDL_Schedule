# migration_phase_splitter.py

Split a MySQL migration into canary-safe phases and statement-level units.

## Input
- Forward migration file: `YYYY-MM-DD_name.sql`
- Optional rollback file: `YYYY-MM-DD_name.rollback.sql`

## Run
```bash
python3 migration_phase_splitter.py \
  --forward /path/to/2026-04-16_example.sql \
  --rollback /path/to/2026-04-16_example.rollback.sql \
  --out-dir /path/to/split-output
```

## Output
For `2026-04-16_example.sql`:
- `2026-04-16_example.pre.sql`
- `2026-04-16_example.data.sql`
- `2026-04-16_example.post.sql`
- `2026-04-16_example.manual.sql` (only when needed)

Statement-level files:
- `2026-04-16_example.pre.001.sql`
- `2026-04-16_example.post.001.sql`
- etc.

Rollback outputs:
- `2026-04-16_example.pre.rollback.sql`
- `2026-04-16_example.data.rollback.sql`
- `2026-04-16_example.post.rollback.sql`
- `2026-04-16_example.manual.rollback.sql` (only when needed)

Manifest:
- `2026-04-16_example.manifest.json`

## Phase rules (high level)
- `pre`: additive changes (e.g., `CREATE TABLE`, nullable/default `ADD COLUMN`, non-unique index)
- `data`: `INSERT` / `UPDATE` / `DELETE` / backfill
- `post`: destructive or strict constraints (e.g., `DROP`, `FK`, `CHECK`, `UNIQUE`, `NOT NULL` tighten)
- `manual`: mixed or ambiguous statements that should be reviewed before automation
- If forward + rollback both include `ALTER TABLE ... MODIFY COLUMN ... ENUM(...)`, the script infers expansion/shrink and auto-classifies (`expansion -> pre`, `shrink -> post`).

## Strict mode
Fail CI when manual-review statements exist:
```bash
python3 migration_phase_splitter.py --forward /path/to/file.sql --strict
```
