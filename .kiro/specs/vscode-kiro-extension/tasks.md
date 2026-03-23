# Implementation Plan: VS Code Kiro Extension

## Tasks

- [x] 1. Scaffold a standalone VS Code extension folder
  - [x] 1.1 Add `package.json` with commands, activation events, and configuration
  - [x] 1.2 Add `extension.js` as the thin activation layer

- [x] 2. Implement dual-mode workflow primitives
  - [x] 2.1 Create `ModeManager` for `spec` and `vibe`
  - [x] 2.2 Surface the current mode in a status bar item
  - [x] 2.3 Add a command to toggle modes

- [x] 3. Implement filesystem-native spec generation
  - [x] 3.1 Create `SpecBootstrap`
  - [x] 3.2 Generate `requirements.md`, `design.md`, and `tasks.md`

- [x] 4. Implement automatic task detection
  - [x] 4.1 Parse markdown checkbox items
  - [x] 4.2 Parse `TODO`, `FIXME`, and `XXX` markers
  - [x] 4.3 Render a workspace task report

- [x] 5. Implement persistent project memory
  - [x] 5.1 Store memory in `.kiro/kiro-assistant-memory.json`
  - [x] 5.2 Add commands to save memory and open the memory file

- [x] 6. Implement context-aware prompt generation
  - [x] 6.1 Collect bounded workspace snippets
  - [x] 6.2 Include saved memory in prompt context
  - [x] 6.3 Generate Plan, Build, and Improve prompts

- [x] 7. Implement slash-command routing
  - [x] 7.1 Support `/mode`
  - [x] 7.2 Support `/spec`
  - [x] 7.3 Support `/plan`, `/build`, and `/improve`
  - [x] 7.4 Support `/memory`
  - [x] 7.5 Support `/tasks`

- [ ] 8. Wire the extension to an actual model provider
  - [ ] 8.1 Add provider configuration for user-supplied API credentials
  - [ ] 8.2 Connect prompt generation to a chat surface or panel
  - [ ] 8.3 Add integration tests for provider-backed actions

- [x] 9. Add unit tests for core logic
  - [x] 9.1 Test mode persistence and validation
  - [x] 9.2 Test checkbox and inline task parsing
  - [x] 9.3 Test spec creation templates
  - [x] 9.4 Test memory persistence
  - [x] 9.5 Test prompt generation
  - [x] 9.6 Test slash-command routing

- [ ] 10. Package and validate inside VS Code
  - [ ] 10.1 Install dependencies if needed
  - [ ] 10.2 Launch the extension in the VS Code extension host
  - [ ] 10.3 Verify command flows manually
