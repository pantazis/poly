# Requirements Document

## Introduction

This document specifies a standalone VS Code extension that brings Kiro-style workflow primitives into the editor without depending on Kiro itself. The goal is to reproduce the core development loop: spec-first execution when needed, fast iteration when appropriate, persistent project memory, task-driven delivery, and prompt scaffolding that keeps coding context structured.

## Glossary

- **Spec Mode**: Structured workflow that starts from requirements, design, and task files
- **Vibe Mode**: Faster workflow that allows direct build prompts with lighter planning
- **Project Memory**: Persistent workspace-scoped notes stored on disk
- **Spec Bundle**: A folder under `.kiro/specs/<feature>/` containing `requirements.md`, `design.md`, and `tasks.md`
- **Plan Build Improve Loop**: A three-step prompt pipeline for planning work, implementing changes, and refining the result
- **Slash Command**: A text command such as `/spec feature-name` or `/plan improve prompts`

## Requirements

### Requirement 1: Dual-Mode Development

**User Story:** As a developer, I want Spec mode and Vibe mode so I can choose between strict structure and rapid iteration.

#### Acceptance Criteria

1. THE extension SHALL expose a workspace-scoped mode toggle between `spec` and `vibe`
2. THE extension SHALL display the current mode in the VS Code UI
3. WHEN Spec mode is active, THE extension SHALL produce prompts that prioritize requirements, design, tasks, and tests
4. WHEN Vibe mode is active, THE extension SHALL produce prompts that prioritize direct implementation with lighter scaffolding

### Requirement 2: Tasks.md Driven Workflow

**User Story:** As a developer, I want task files with checkboxes so I can track implementation progress in a Kiro-style workflow.

#### Acceptance Criteria

1. THE extension SHALL create `requirements.md`, `design.md`, and `tasks.md` under `.kiro/specs/<feature>/`
2. THE generated `tasks.md` SHALL use markdown checkboxes
3. THE extension SHALL detect open checkbox items from workspace markdown files
4. THE extension SHALL summarize open task counts for the current workspace

### Requirement 3: Context-Aware Coding

**User Story:** As a developer, I want prompts built from the current workspace so generated plans and code requests stay grounded in local context.

#### Acceptance Criteria

1. THE extension SHALL collect snippets from relevant workspace files
2. THE extension SHALL include project memory entries in prompt context when available
3. THE extension SHALL make the context size configurable
4. THE extension SHALL generate prompts that include the workspace name, selected mode, memory, and file snippets

### Requirement 4: Persistent Project Memory

**User Story:** As a developer, I want persistent project memory so repeated prompts carry forward architectural decisions and conventions.

#### Acceptance Criteria

1. THE extension SHALL persist project memory to `.kiro/kiro-assistant-memory.json`
2. THE extension SHALL support saving named memory entries
3. THE extension SHALL reopen the memory file inside VS Code
4. THE extension SHALL include persisted memory in prompt generation

### Requirement 5: Spec -> Code Pipeline

**User Story:** As a developer, I want a spec-to-code pipeline so planning and implementation stay connected.

#### Acceptance Criteria

1. THE extension SHALL generate separate Plan, Build, and Improve prompts
2. THE prompts SHALL reflect the active workflow mode
3. THE prompts SHALL instruct the user to update specs or tasks when behavior changes
4. THE prompts SHALL call out testing expectations

### Requirement 6: Slash Commands and Agent Actions

**User Story:** As a developer, I want slash commands so common workflow actions are quick to trigger.

#### Acceptance Criteria

1. THE extension SHALL support `/mode`
2. THE extension SHALL support `/spec`
3. THE extension SHALL support `/plan`, `/build`, and `/improve`
4. THE extension SHALL support `/memory`
5. THE extension SHALL support `/tasks`

### Requirement 7: Automatic Task Detection

**User Story:** As a developer, I want the extension to find pending work automatically so I can see open tasks without manual tracking.

#### Acceptance Criteria

1. THE extension SHALL detect markdown checklist items
2. THE extension SHALL detect inline `TODO`, `FIXME`, and `XXX` markers
3. THE extension SHALL report the source file and line number for each detected task

### Requirement 8: Modular System Architecture

**User Story:** As a maintainer, I want the extension built from small services so the workflow can evolve without rewriting the plugin.

#### Acceptance Criteria

1. THE extension SHALL separate mode state, memory, spec bootstrapping, task detection, context collection, prompt generation, and command routing
2. THE core workflow services SHALL be testable without launching VS Code
3. THE extension activation layer SHALL be thin and delegate to core services

### Requirement 9: Built-in Prompt Engineering

**User Story:** As a developer, I want repeatable prompt templates so the extension produces consistent instructions.

#### Acceptance Criteria

1. THE extension SHALL provide prompt templates for planning, implementation, and review
2. THE planning prompt SHALL mention impacted files, specs, tasks, and tests
3. THE build prompt SHALL mention smallest-complete-slice implementation and test updates
4. THE improve prompt SHALL mention regressions, weak assumptions, and next-step refinement

### Requirement 10: Iterative Development Loop

**User Story:** As a developer, I want a Plan -> Build -> Improve loop so the editor keeps work moving in a disciplined cycle.

#### Acceptance Criteria

1. THE extension SHALL expose a command that generates the full Plan -> Build -> Improve prompt set
2. THE extension SHALL allow the same goal to flow through all three stages
3. THE generated prompts SHALL be viewable inside VS Code

### Requirement 11: Unit-Tested Core Logic

**User Story:** As a maintainer, I want unit tests for the workflow engine so refactors do not break the editor behavior.

#### Acceptance Criteria

1. THE extension SHALL include unit tests for mode state
2. THE extension SHALL include unit tests for task parsing
3. THE extension SHALL include unit tests for spec bootstrapping
4. THE extension SHALL include unit tests for project memory persistence
5. THE extension SHALL include unit tests for prompt generation
6. THE extension SHALL include unit tests for slash-command routing
