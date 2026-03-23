# Test Planning

## Purpose

Create a validation plan for requirements, design decisions, checkpoints, and property-style invariants that appear in this repository's Kiro specs.

## When To Use

- When a design defines invariants or universal rules
- When a task plan mentions checkpoints or validation gates
- When feature work needs explicit test coverage before or alongside implementation
- When reviewing whether acceptance criteria are actually testable

## Inputs Expected

- Requirements document
- Design document
- Implementation plan
- Existing tests and testing tools in the repository

## Rules And Non-Goals

- Do not invent behavior outside the requirements or design.
- Do not limit validation to happy-path tests.
- Prefer deterministic, automatable checks.
- Use property-style tests only when invariants genuinely exist.

## Procedure

1. Extract acceptance criteria from requirements.
2. Extract invariants, error cases, retries, limits, and state rules from the design.
3. Map them to concrete test types:
   - unit
   - async unit
   - integration
   - property-style
   - manual verification when automation is not practical
4. Identify missing observability or seams that would block testing.
5. Organize validation by checkpoint as well as by requirement.

## Output Format

```md
# Test Plan: <feature>
## Coverage Matrix
- Requirement or property -> test type -> target file/module
## Checkpoint Validation
- Checkpoint -> required evidence
## Gaps
- Missing seams, fixtures, mocks, or data
## Priority Order
- Must have
- Should have
- Optional
```

## Quality Gates

- Every key requirement has a validation path.
- Design invariants are not lost in implementation planning.
- Checkpoints have explicit evidence.
- Testing gaps are called out before coding or release.