const { MODES } = require("./modeManager");

class PromptBuilder {
  buildPlanBuildImprove(goal, contextBundle, mode) {
    return {
      plan: this.buildPlanPrompt(goal, contextBundle, mode),
      build: this.buildBuildPrompt(goal, contextBundle, mode),
      improve: this.buildImprovePrompt(goal, contextBundle, mode)
    };
  }

  buildPlanPrompt(goal, contextBundle, mode = MODES.SPEC) {
    const workflow = mode === MODES.SPEC
      ? "Start from requirements, design, and tasks before proposing code."
      : "Prefer a lightweight execution plan and move quickly to implementation.";

    return [
      `Goal: ${goal}`,
      `Mode: ${mode}`,
      workflow,
      "Plan output requirements:",
      "- Identify impacted files and system boundaries",
      "- Name missing specs, tasks, or tests",
      "- Break work into reviewable steps",
      "",
      formatContext(contextBundle)
    ].join("\n");
  }

  buildBuildPrompt(goal, contextBundle, mode = MODES.SPEC) {
    return [
      `Goal: ${goal}`,
      `Mode: ${mode}`,
      "Build output requirements:",
      "- Implement the smallest complete slice first",
      "- Preserve the current architecture unless the plan says otherwise",
      "- Update specs or task files when behavior changes",
      "- Add or update tests for the changed logic",
      "",
      formatContext(contextBundle)
    ].join("\n");
  }

  buildImprovePrompt(goal, contextBundle, mode = MODES.SPEC) {
    return [
      `Goal: ${goal}`,
      `Mode: ${mode}`,
      "Improve output requirements:",
      "- Review for regressions, missing tests, and weak assumptions",
      "- Tighten prompts, tasks, and memory entries",
      "- Suggest the next iteration only if it materially improves the workflow",
      "",
      formatContext(contextBundle)
    ].join("\n");
  }
}

function formatContext(contextBundle) {
  const files = contextBundle.files.map((file) => {
    return `File: ${file.path}\n${file.snippet}`;
  }).join("\n\n");

  const memory = contextBundle.memory.length > 0
    ? contextBundle.memory.map((entry) => `- ${entry.key}: ${entry.value}`).join("\n")
    : "- none";

  return [
    "Context:",
    `Workspace: ${contextBundle.workspaceName}`,
    "Memory:",
    memory,
    "Files:",
    files || "No files captured"
  ].join("\n");
}

module.exports = {
  PromptBuilder,
  formatContext
};
