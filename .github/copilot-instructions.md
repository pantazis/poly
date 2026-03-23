# Copilot Instructions

## Purpose

This repository uses a Kiro-style, requirements-first workflow. Mirror that workflow with GitHub Copilot using only supported customization files under `.github/`.

## Default Working Mode

1. Plan before coding.
2. Separate work into requirements, design, implementation plan, implementation, and validation.
3. Clarify missing or ambiguous requirements before making behavior-changing edits.
4. Maintain traceability from requirement to design to task to code to test.
5. Prefer the smallest complete slice that can be validated.

## Repository Workflow Rules

1. Treat `.kiro/specs/<feature>/requirements.md`, `design.md`, and `tasks.md` as the source workflow model for structured work.
2. Preserve the existing pattern of explicit acceptance criteria in requirements.
3. Preserve the existing pattern of `Validates: Requirements ...` markers in design and validation output.
4. Preserve the existing pattern of task entries referencing specific requirements for traceability.
5. Use checkpoints when a change spans multiple components or stages.
6. If a task is implementation-only and the relevant spec bundle is missing or outdated, call that out before coding.

## Engineering Constraints

1. Keep changes minimal and local to the feature being changed.
2. Follow the current Python code style already used in `src/` and `tests/`:
   - Python 3.11+
   - type hints
   - concise module and test docstrings where already present
   - pytest-based tests, including `pytest.mark.asyncio` for async behavior
3. Prefer existing project dependencies before adding new ones.
4. Keep entry points thin and move logic into testable modules.
5. Preserve the current separation between collector code in `src/` and trading-specific code in `src/trading/`.
6. Default to safe behavior for operational or trading changes. Do not silently weaken dry-run, logging, validation, or risk controls.

## Spec-First Behavior

When the task is feature work, behavioral change, refactoring with user-visible impact, or architecture work:

1. Check whether the relevant requirements, design, and tasks already exist.
2. If they do not exist or are incomplete, produce or request the missing stage before coding.
3. Do not jump from a vague request directly into implementation.
4. Require acceptance criteria that are testable and unambiguous.
5. Require explicit assumptions when external APIs, configuration, or runtime behavior are uncertain.

## Implementation Rules

1. Implement against the approved or current design, not against unstated assumptions.
2. Keep task ordering incremental:
   - foundations and data models first
   - isolated components next
   - orchestration and wiring after that
   - final integration validation last
3. Update related tests when behavior changes.
4. If a design describes validation properties or invariants, include tests or validation steps that cover them.
5. Call out requirement, design, or task drift if code changes no longer match the documented workflow.

## Validation Expectations

1. Validate every behavior-changing change against acceptance criteria.
2. Include a traceability summary when useful:
   - implemented requirements
   - design sections affected
   - tasks completed or invalidated
   - tests added or updated
3. Prefer deterministic validation:
   - unit tests
   - async tests for async behavior
   - property-style tests when the design defines invariants or universal rules
4. If validation could not be completed, state the exact gap and the residual risk.

## When To Use Prompts And Skills

1. Use prompt files in `.github/prompts/` when the user asks for requirements, design, planning, or spec validation.
2. Use the skills in `.github/skills/` to keep output procedural and stage-specific.
3. Prefer:
   - `spec-authoring` for requirements creation or refinement
   - `design-review` for design derivation and design checks
   - `implementation-planner` for task plans and sequencing
   - `change-validator` for implementation review against specs
   - `test-planning` when the design implies invariants, checkpoints, or property-style validation

## Response Style For Structured Work

1. Use compact sections and checklists.
2. Be explicit about missing inputs, assumptions, and decision gates.
3. Avoid fluffy prose.
4. Prefer deterministic output formats over freeform narrative.