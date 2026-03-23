const fs = require("fs/promises");
const path = require("path");

function slugify(value) {
  return value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

class SpecBootstrap {
  constructor(workspaceRoot) {
    this.workspaceRoot = workspaceRoot;
  }

  async createSpec(name) {
    const slug = slugify(name);
    const dir = path.join(this.workspaceRoot, ".kiro", "specs", slug);
    await fs.mkdir(dir, { recursive: true });

    const files = {
      requirements: path.join(dir, "requirements.md"),
      design: path.join(dir, "design.md"),
      tasks: path.join(dir, "tasks.md")
    };

    await fs.writeFile(files.requirements, buildRequirementsTemplate(name), "utf8");
    await fs.writeFile(files.design, buildDesignTemplate(name), "utf8");
    await fs.writeFile(files.tasks, buildTasksTemplate(name), "utf8");

    return files;
  }
}

function buildRequirementsTemplate(name) {
  return `# Requirements Document

## Introduction

This document defines the requirements for ${name}.

## Requirements

### Requirement 1: Dual-Mode Workflow

**User Story:** As a developer, I want Spec mode and Vibe mode so I can choose between structured execution and fast iteration.

#### Acceptance Criteria

1. THE extension SHALL expose a mode toggle between \`spec\` and \`vibe\`
2. THE extension SHALL persist the selected mode per workspace
3. WHEN Spec mode is active, THE extension SHALL prefer spec-first prompts and workflows
4. WHEN Vibe mode is active, THE extension SHALL prefer direct build prompts and lighter structure
`;
}

function buildDesignTemplate(name) {
  return `# Design Document: ${name}

## Overview

${name} follows a Kiro-style workflow inside VS Code using modular services for mode state, spec bootstrapping, task detection, memory, and prompt generation.

## Architecture

\`\`\`mermaid
flowchart LR
  UI[VS Code Commands] --> MODE[ModeManager]
  UI --> SPEC[SpecBootstrap]
  UI --> TASKS[TaskDetector]
  UI --> MEMORY[MemoryStore]
  UI --> PROMPTS[PromptBuilder]
  PROMPTS --> CONTEXT[ContextCollector]
\`\`\`

## Notes

- Use \`.kiro/specs/<feature>\` for spec artifacts
- Store persistent memory in \`.kiro/kiro-assistant-memory.json\`
- Keep slash commands thin and route them through shared services
`;
}

function buildTasksTemplate(name) {
  return `# Implementation Plan: ${name}

## Tasks

- [ ] 1. Add dual-mode workflow and status display
- [ ] 2. Bootstrap requirements, design, and tasks files
- [ ] 3. Detect markdown checkboxes, TODO, and FIXME items
- [ ] 4. Persist project memory to disk
- [ ] 5. Build plan, build, and improve prompt templates
- [ ] 6. Route slash commands to shared actions
- [ ] 7. Add unit tests for parsing, prompts, memory, and mode state
`;
}

module.exports = {
  SpecBootstrap,
  slugify
};
