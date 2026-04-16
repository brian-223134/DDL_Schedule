---
name: target-review
description: Review specific files explicitly mentioned in the current chat. Use when the user invokes `target_review` or `target-review`, or asks for code review of named files, paths, snippets, or diffs and expects review findings rather than implementation. If no target file is mentioned, ask for the file path before reviewing.
---

# Target Review

## Workflow

1. Identify the review target from the current chat. Accept explicit paths, filenames, attached snippets, or diffs. If the target is ambiguous, ask one concise clarification question.
2. Keep the scope centered on the mentioned files. Read adjacent callers, tests, schemas, or generated outputs only when needed to verify a concrete risk.
3. Do not edit files, stage changes, or create commits unless the user explicitly asks for fixes after the review.
4. Prioritize findings that can cause incorrect behavior, data loss, security exposure, migration failure, rollback failure, concurrency issues, or broken tests.
5. Check whether existing tests cover the risky behavior. If tests are absent or incomplete, report that as a testing gap only when it affects confidence in the change.

## Review Output

- Put findings first, ordered by severity.
- Use tight file and line references for each finding.
- Explain the concrete failure mode and the condition that triggers it.
- Avoid broad style feedback unless it creates a maintainability risk that can realistically cause defects.
- If there are no findings, state that explicitly and include residual risks or areas not reviewed.
- Add open questions or assumptions only after findings.

## Codex Desktop Inline Findings

When emitting inline review findings in Codex Desktop, use one `::code-comment` directive per finding with an absolute file path and a tight line range. Keep each directive focused on one issue.
