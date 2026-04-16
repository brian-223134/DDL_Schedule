---
name: make-plan
description: Create an implementation or investigation plan from the user's proposal, requirement, or idea. Use when the user invokes `make_plan` or `make-plan`, or asks for a plan before coding. The expected output is a plan only; do not modify files unless the user later asks to implement.
---

# Make Plan

## Workflow

1. Extract the objective, constraints, target files, and success criteria from the user's latest proposal and relevant chat context.
2. Inspect the repository only as much as needed to make the plan concrete. Prefer `rg`, `rg --files`, and short file reads.
3. State assumptions instead of asking questions when a reasonable assumption is safe. Ask one concise clarification question only when the plan would be misleading without the answer.
4. Do not edit files, stage changes, create commits, or run destructive commands while using this skill.
5. If the plan involves code changes, name likely files or modules to inspect or modify and include validation commands.

## Plan Output

Structure the plan so the user can approve, reject, or modify it quickly:

- Goal: one sentence describing the intended outcome.
- Assumptions: concrete assumptions that affect the plan.
- Scope: what is included and what is intentionally excluded.
- Steps: ordered implementation or investigation steps.
- Validation: tests, scripts, review checks, or manual verification.
- Risks: edge cases, migration concerns, rollback issues, or unresolved decisions.

Keep the plan concise, but make each step actionable enough that another Codex session could execute it.
