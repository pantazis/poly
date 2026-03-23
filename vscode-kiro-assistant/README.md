# vscode-kiro-assistant

`vscode-kiro-assistant` is a local VS Code extension that brings a Kiro-style development workflow into the editor. Its purpose is to help a developer or coding LLM work in two modes:

- `spec` mode: requirements-first, design-first, task-first execution
- `vibe` mode: lighter planning and faster iteration

The extension does not call an LLM by itself. Instead, it generates structure, project context, and prompt text that can be passed to another assistant.

## What it does

The extension adds a small workflow layer on top of VS Code:

- toggles between `spec` and `vibe` modes
- bootstraps spec files under `.kiro/specs/<feature>/`
- scans the workspace for markdown checklist items and inline `TODO` / `FIXME` / `XXX` tasks
- stores persistent project memory in `.kiro/kiro-assistant-memory.json`
- builds `Plan`, `Build`, and `Improve` prompts from workspace context
- supports slash commands for the same actions

## Commands exposed in VS Code

Registered commands:

- `kiroAssistant.toggleMode`
- `kiroAssistant.bootstrapSpec`
- `kiroAssistant.scanTasks`
- `kiroAssistant.planBuildImprove`
- `kiroAssistant.runSlashCommand`
- `kiroAssistant.saveProjectMemory`
- `kiroAssistant.openProjectMemory`

User-facing titles:

- `Kiro Assistant: Toggle Mode`
- `Kiro Assistant: Create Spec`
- `Kiro Assistant: Scan Tasks`
- `Kiro Assistant: Plan Build Improve`
- `Kiro Assistant: Run Slash Command`
- `Kiro Assistant: Save Project Memory`
- `Kiro Assistant: Open Project Memory`

## Slash commands

The slash command router supports:

- `/mode [spec|vibe]`
- `/spec <feature-name>`
- `/plan <goal>`
- `/build <goal>`
- `/improve <goal>`
- `/memory key=value`
- `/tasks`

Unknown commands return a simple error message.

## Workspace artifacts

The extension writes its state into the current workspace:

- `.kiro/specs/<slug>/requirements.md`
- `.kiro/specs/<slug>/design.md`
- `.kiro/specs/<slug>/tasks.md`
- `.kiro/kiro-assistant-memory.json`

Spec creation uses a fixed starter template. The generated spec always includes:

- a requirements document
- a design document with a small architecture diagram
- a tasks checklist

## Prompt generation model

Prompt generation is handled by `PromptBuilder`. It produces three prompt types:

- `plan`: identify impacted files, boundaries, missing tests/specs, and reviewable steps
- `build`: implement the smallest complete slice, preserve architecture, update tests/specs
- `improve`: review regressions, missing tests, weak assumptions, and next workflow iteration

Prompts include:

- workspace name
- selected snippets from important files
- saved project memory entries
- current mode (`spec` or `vibe`)

In `spec` mode, prompts bias toward requirements/design/tasks first. In `vibe` mode, prompts bias toward lightweight planning and faster implementation.

## Context collection

`ContextCollector` gathers a bounded amount of context from likely-important files:

- `.kiro/kiro-assistant-memory.json`
- `.kiro/`
- `README.md`
- `package.json`
- `src/`
- `tests/`

The amount of context is controlled by extension settings:

- `kiroAssistant.maxContextFiles` default: `6`
- `kiroAssistant.maxSnippetLength` default: `1200`

## Architecture

Main entrypoint:

- `extension.js`

Core services:

- `ModeManager`: persists `spec` vs `vibe` mode in VS Code workspace state
- `MemoryStore`: reads/writes `.kiro/kiro-assistant-memory.json`
- `SpecBootstrap`: creates spec folders and starter markdown files
- `TaskDetector`: scans workspace files for checklists and inline task markers
- `TaskParser`: parses markdown checkboxes and `TODO` / `FIXME` / `XXX`
- `ContextCollector`: collects bounded file snippets and memory for prompts
- `PromptBuilder`: builds plan/build/improve prompts
- `CommandRouter`: maps slash commands to shared services

## Important behavioral limits

- This project is a workflow assistant, not a full autonomous agent.
- It does not execute code changes on its own.
- It does not talk to external LLM APIs.
- It relies on the open workspace folder; without one, the extension warns and does nothing.
- Task scanning ignores `.git` and `node_modules`.

## Tests

Tests live in `test/` and cover the main workflow pieces:

- mode switching
- memory storage
- prompt generation
- command routing
- task parsing
- spec bootstrapping

Run them with:

```bash
npm test
```

## Short summary for an LLM

If you need the shortest accurate description of this project:

> `vscode-kiro-assistant` is a VS Code extension that helps structure coding work in a Kiro-like workflow. It manages `spec` vs `vibe` mode, creates spec documents, scans tasks, stores project memory, and generates plan/build/improve prompts from local workspace context. It is a prompt-and-workflow orchestration tool, not an LLM client.
