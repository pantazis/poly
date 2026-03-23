# Design Review

## Purpose

Produce or review a design document that converts approved requirements into an implementable architecture with explicit validation mapping.

## When To Use

- After requirements are approved
- Before implementation planning
- When reviewing whether code structure still matches documented design
- When the change introduces new components, interfaces, or failure modes

## Inputs Expected

- Requirements document
- Relevant codebase files and module structure
- Existing related design docs under `.kiro/specs/`
- Operational, runtime, and integration constraints

## Rules And Non-Goals

- Do not skip requirements review.
- Do not collapse design into task lists.
- Avoid speculative architecture with no requirement driver.
- Keep component boundaries simple and testable.

## Procedure

1. Read the requirements and extract the behaviors that need architecture support.
2. Reuse repository component naming and boundaries where practical.
3. Document key design decisions and why they exist.
4. Define data flow, interfaces, state transitions, and error handling.
5. Add validation entries that map design sections, properties, or scenarios back to requirement IDs.
6. Identify open questions or risky assumptions.

## Output Format

```md
# Design Document: <feature>
## Overview
## Key Design Decisions
## Architecture
## Components And Interfaces
## Failure Modes And Recovery
## Testing Strategy
## Validation Mapping
## Open Questions
```

## Quality Gates

- Every major component traces back to a requirement.
- Failure modes and recovery behavior are documented.
- Validation mapping is explicit.
- The design can be implemented incrementally.