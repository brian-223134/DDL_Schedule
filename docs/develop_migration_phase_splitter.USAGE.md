# develop/migration_phase_splitter.py

Split a MySQL develop migration into simple deploy-before/deploy-after files.

Detailed code explanation:
- [`develop_migration_phase_splitter.DETAILS.md`](./develop_migration_phase_splitter.DETAILS.md)

## Input
- Source SQL file: `YYYY-MM-DD_name.sql`

## Run
```bash
python3 develop/migration_phase_splitter.py \
  --input /path/to/2026-04-16_example.sql \
  --out-dir /path/to/develop-split-output
```

`--forward` is also accepted as an alias for `--input`.

## Output
For `2026-04-16_example.sql`:
- `2026-04-16_example.pre.sql`
- `2026-04-16_example.post.sql`

Statement-level files:
- `2026-04-16_example.pre.001.sql`
- `2026-04-16_example.post.001.sql`
- etc.

Manifest:
- `2026-04-16_example.manifest.json`

## Develop Phase Rules
- `pre`: `CREATE` statements, except permission/account control statements such as `CREATE USER` or `CREATE ROLE`
- `post`: `DROP`, permission/account control, data statements, and ambiguous statements

Develop mode intentionally does not create a separate `data` or `manual` phase. Anything that is not an obvious `CREATE` statement is emitted to `post`.
