# Validate Against Spec

## When To Use

Use this prompt after implementation or during review to verify that changes still match requirements, design, and plan.

## Required Inputs

- Requirements document
- Design document
- Implementation plan or task list
- Changed files or proposed changes
- Test results or validation evidence if available

## Process

1. Compare changed behavior against requirements.
2. Compare implementation structure against the design.
3. Check whether completed work matches the intended task sequence.
4. Identify omissions, regressions, undocumented behavior, and stale specs.
5. Check whether required tests or validation evidence exist.
6. Produce findings first, then a coverage summary.

## Output Structure

```md
# Validation Report: <feature or change>

## Findings
1. Severity: <high|medium|low>
   - Requirement or design reference: ...
   - Evidence: ...
   - Gap: ...

## Coverage Summary
- Implemented requirements: ...
- Partially implemented requirements: ...
- Missing requirements: ...
- Design drift: ...
- Task drift: ...

## Test And Validation Status
- Tests present: ...
- Tests missing: ...
- Property-style coverage: ...

## Required Follow-Ups
1. ...
2. ...
```

## Rules

- Lead with concrete findings, not a summary.
- Distinguish implementation bugs from documentation drift.
- State when evidence is missing instead of assuming compliance.
- Use precise requirement and design references.

## Quality Gates

- Findings are evidence-based.
- Coverage status is explicit.
- Missing validation is called out.
- Follow-ups are actionable.