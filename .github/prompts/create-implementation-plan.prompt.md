# Create Implementation Plan

## When To Use

Use this prompt after requirements and design are available and implementation needs to be sequenced into tasks.

## Required Inputs

- Requirements document
- Design document
- Relevant repository structure
- Existing tests and checkpoints
- Delivery constraints such as MVP scope or sequencing preferences

## Process

1. Read requirements and design before creating tasks.
2. Break work into incremental tasks that can be validated independently.
3. Put foundational models and configuration before higher-level orchestration.
4. Reference the requirements covered by each task.
5. Add validation or checkpoint tasks where the design suggests them.
6. Mark optional work explicitly rather than mixing it into critical path tasks.
7. Keep tasks implementation-ready and file-aware.

## Output Structure

```md
# Implementation Plan: <feature>

## Overview
- Goal
- Sequencing rationale

## Tasks
- [ ] 1. <task group>
  - [ ] 1.1 <task>
    - Files: ...
    - Outcome: ...
    - Requirements: ...
  - [ ] 1.2 <task>
    - Files: ...
    - Outcome: ...
    - Validates: ...

- [ ] 2. <task group>
...

## Checkpoints
- Checkpoint name: what must be verified

## Notes
- Optional tasks
- Risks
- Dependencies
```

## Rules

- Do not create tasks that cannot be tied to requirements or design.
- Do not hide validation at the end only; place checkpoints through the plan.
- Prefer the smallest complete slice over wide parallel churn.
- Mention impacted files or modules when they are known.

## Quality Gates

- Task order is incremental and defensible.
- Every task references requirements, validation, or both.
- The plan exposes checkpoints.
- Optional work is clearly separated.