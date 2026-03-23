# Change Validator

## Purpose

Review a change against requirements, design, tasks, and tests using the repository's Kiro-style traceability rules.

## When To Use

- After implementation
- During code review
- When a spec may be stale
- When checking whether a task was completed correctly

## Inputs Expected

- Requirements document
- Design document
- Implementation plan or task list
- Changed files or diff summary
- Test results if available

## Rules And Non-Goals

- Lead with findings.
- Separate bugs from spec drift.
- Do not assume compliance without evidence.
- Do not hide missing validation.

## Procedure

1. Compare behavior in the change to each relevant requirement.
2. Compare structure and control flow to the design.
3. Compare delivered work to the implementation plan and checkpoints.
4. Check whether tests cover acceptance criteria and design invariants.
5. Classify gaps as implementation defects, missing validation, or documentation drift.
6. Summarize coverage after listing findings.

## Output Format

```md
# Validation Report: <change>
## Findings
## Coverage Summary
## Test And Validation Status
## Required Follow-Ups
```

## Quality Gates

- Findings are evidence-based.
- Requirement, design, and task references are explicit.
- Missing tests or validation are called out.
- Follow-up actions are concrete.