# Spec Authoring

## Purpose

Produce or refine a requirements document that matches this repository's Kiro-style spec workflow.

## When To Use

- New feature requests
- Behavioral changes that need acceptance criteria
- Refactors that change externally visible behavior
- Cases where coding would otherwise start from ambiguous goals

## Inputs Expected

- Feature name
- Goal and problem statement
- Scope and non-goals
- Existing related specs under `.kiro/specs/`
- Relevant codebase context
- External integrations, constraints, and safety concerns

## Rules And Non-Goals

- Stay in the requirements stage.
- Do not generate design or implementation tasks here.
- Do not guess missing external behavior.
- Reuse repository terminology when it exists.
- Make every requirement testable.

## Procedure

1. Inspect relevant `.kiro/specs/` bundles for naming, structure, and related behavior.
2. Identify whether the request extends existing functionality or introduces new functionality.
3. Write a short introduction and glossary only when they add precision.
4. Create numbered requirements with one user story per requirement.
5. Add explicit acceptance criteria under each requirement.
6. Record open questions and assumptions separately.
7. Stop if critical inputs are missing.

## Output Format

```md
# Requirements Document: <feature>
## Introduction
## Glossary
## Requirements
### Requirement N: <name>
**User Story:** ...
#### Acceptance Criteria
1. ...
## Open Questions
## Assumptions
```

## Quality Gates

- Requirements are numbered and scoped.
- Acceptance criteria are observable and testable.
- Terminology matches the repo and existing specs.
- Open questions and assumptions are separated from accepted behavior.