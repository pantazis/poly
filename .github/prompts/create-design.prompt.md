# Create Design

## When To Use

Use this prompt after requirements exist and before implementation tasks are planned.

## Required Inputs

- Approved requirements document
- Relevant codebase context
- Existing architecture constraints
- Runtime, API, storage, and operational considerations
- Known risks and failure modes

## Process

1. Read the requirements first.
2. Derive the architecture, components, interfaces, data flow, and failure handling from the requirements.
3. Make major design decisions explicit.
4. Define validation points that map back to requirements.
5. Include test strategy or property-style validation when the design introduces invariants.
6. If requirements are underspecified, stop and list the gaps.

## Output Structure

```md
# Design Document: <feature>

## Overview
- Summary
- Key constraints
- Important safety notes

## Key Design Decisions
1. ...
2. ...

## Architecture
- Components
- Boundaries
- Data flow

## Components And Interfaces
### <Component>
- Responsibility
- Inputs
- Outputs
- Errors

## Failure Modes And Recovery
- ...

## Testing Strategy
- Unit tests
- Integration tests
- Property-style tests if applicable

## Validation Mapping
- Design section or property -> Validates: Requirements x.y, z.y

## Open Questions
- ...
```

## Rules

- Do not skip the mapping back to requirements.
- Do not write implementation tasks in this stage.
- Prefer simple, testable component boundaries.
- Include operational safety behavior when external systems are involved.

## Quality Gates

- Every major component exists for a requirement-driven reason.
- The design can be implemented incrementally.
- Failure handling is covered.
- Validation markers reference concrete requirements.