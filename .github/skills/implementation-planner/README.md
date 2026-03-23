# Implementation Planner

## Purpose

Turn approved requirements and design into a traceable implementation plan with incremental tasks and checkpoints.

## When To Use

- After requirements and design are available
- Before coding a multi-file or behavior-changing change
- When a feature needs staged delivery instead of direct editing

## Inputs Expected

- Requirements document
- Design document
- Current repository structure
- Known MVP constraints or optional scope
- Existing tests and validation expectations

## Rules And Non-Goals

- Do not plan from vague goals alone.
- Do not create tasks that lack requirement or design grounding.
- Do not put all validation at the end.
- Keep the critical path clear and small.

## Procedure

1. Read the requirements and design together.
2. Group work into foundations, components, orchestration, and validation.
3. Sequence tasks so each stage can be validated before the next.
4. Add requirement references to each task or subtask.
5. Add checkpoint tasks for integration, risk, or safety-sensitive transitions.
6. Mark optional tasks clearly when they are not on the MVP path.
7. Mention concrete files or modules when known.

## Output Format

```md
# Implementation Plan: <feature>
## Overview
## Tasks
## Checkpoints
## Notes
```

## Quality Gates

- Task order is incremental.
- Each task has traceability.
- Validation is distributed across the plan.
- Optional work is clearly labeled.