const { MODES } = require("./modeManager");

class CommandRouter {
  constructor(services) {
    this.services = services;
  }

  async run(input) {
    const [command, ...args] = input.trim().split(/\s+/);
    const value = args.join(" ").trim();

    switch (command) {
      case "/mode":
        return this.handleMode(value);
      case "/spec":
        return this.handleSpec(value);
      case "/plan":
        return this.handlePrompt("Plan", value, "plan");
      case "/build":
        return this.handlePrompt("Build", value, "build");
      case "/improve":
        return this.handlePrompt("Improve", value, "improve");
      case "/memory":
        return this.handleMemory(value);
      case "/tasks":
        return this.handleTasks();
      default:
        return {
          kind: "message",
          message: `Unknown slash command: ${command}`
        };
    }
  }

  async handleMode(value) {
    const nextMode = value || (this.services.modeManager.getMode() === MODES.SPEC ? MODES.VIBE : MODES.SPEC);
    await this.services.modeManager.setMode(nextMode);
    return {
      kind: "message",
      message: `Mode set to ${nextMode}`
    };
  }

  async handleSpec(value) {
    if (!value) {
      return {
        kind: "message",
        message: "Usage: /spec <feature-name>"
      };
    }

    await this.services.specBootstrap.createSpec(value);
    return {
      kind: "message",
      message: `Created spec for ${value}`
    };
  }

  async handlePrompt(title, goal, key) {
    const context = await this.services.contextCollector.collect();
    const prompts = this.services.promptBuilder.buildPlanBuildImprove(goal || "Refine the current workspace", context, this.services.modeManager.getMode());
    return {
      kind: "prompt",
      title: `${title} Prompt`,
      message: `${title} prompt generated`,
      body: prompts[key]
    };
  }

  async handleMemory(value) {
    const [key, ...rest] = value.split("=");
    if (!key || rest.length === 0) {
      return {
        kind: "message",
        message: "Usage: /memory key=value"
      };
    }

    await this.services.memoryStore.set(key.trim(), rest.join("=").trim());
    return {
      kind: "message",
      message: `Saved memory: ${key.trim()}`
    };
  }

  async handleTasks() {
    const findings = await this.services.taskDetector.scanWorkspace();
    return {
      kind: "message",
      message: `Open checklist items: ${findings.checklistItems.filter((item) => !item.checked).length}, inline tasks: ${findings.inlineTasks.length}`
    };
  }
}

module.exports = {
  CommandRouter
};
