# Codex Project Instructions

## Scope

These instructions apply to this repository. Prefer repo-local instructions and skills before using broader personal defaults.

## Repo-Local Skills

This repository keeps shared Codex skills under `.codex/skills`. Use these skills by reading the matching `SKILL.md` when the user explicitly invokes the trigger name or when the request clearly matches the described workflow.

- `target_review` / `target-review`: Use `.codex/skills/target-review/SKILL.md` when the user asks for a code review of files mentioned in the chat.
- `make_plan` / `make-plan`: Use `.codex/skills/make-plan/SKILL.md` when the user asks for a plan based on the proposal or requirements they described.

## Skill Routing Rules

- If the user invokes `target_review`, identify the files mentioned in the current chat and perform a review-only pass. Do not edit files unless the user explicitly asks for fixes.
- If the user invokes `make_plan`, produce a plan only. Do not implement, edit files, stage changes, or create commits until the user asks to proceed.
- If a trigger is invoked but the required target is missing or ambiguous, ask one concise clarification question.
- For repo-local skills to be auto-discovered by Codex outside this repository, run `scripts/install-codex-skills.sh` to copy them into `${CODEX_HOME:-$HOME/.codex}/skills`.

## General Working Rules

- Prefer `rg` for searching text and `rg --files` for listing files.
- Treat `split-output-*` directories as generated migration output unless the user specifically asks to inspect or change them.
- Do not run destructive git commands or delete generated outputs unless explicitly requested.
- Keep responses concise and action-oriented. For reviews, findings come first. For plans, assumptions and validation steps must be explicit.
