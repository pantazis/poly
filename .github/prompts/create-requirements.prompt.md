# Create Requirements

## When To Use

Use this prompt when a feature, refactor, integration, or workflow change needs a requirements document before design or coding.

## Required Inputs

- Feature or change name
- Problem statement
- Scope in bounds
- Scope out of bounds
- Existing components, files, or specs that must be respected
- External systems or APIs involved
- Constraints, risks, and operational safety requirements

## Process

1. Read existing `.kiro/specs/` bundles and relevant repository files.
2. Reuse existing terminology and component names where possible.
3. Identify missing information and ask for it instead of guessing.
4. Write requirements as numbered user stories with explicit acceptance criteria.
5. Make acceptance criteria observable and testable.
6. Call out assumptions, dependencies, and safety constraints.
7. If the change extends an existing feature, separate inherited behavior from new behavior.

## Output Structure

```md
# Requirements Document: <feature>

## Introduction
- Goal
- Context
- Safety or operational notes

## Glossary
- Term: definition

## Requirements

### Requirement 1: <name>
**User Story:** As a <role>, I want <capability>, so that <outcome>.

#### Acceptance Criteria
1. ...
2. ...

### Requirement 2: <name>
...

## Open Questions
- ...

## Assumptions
- ...
```

## Rules

- Do not produce design or tasks in this stage.
- Do not write code.
- Do not leave acceptance criteria implicit.
- Do not merge separate concerns into one requirement when traceability would suffer.

## Quality Gates

- Every requirement has a user story.
- Every requirement has acceptance criteria.
- Acceptance criteria are testable.
- Terms are consistent with the repository.
- Missing information is explicitly listed.