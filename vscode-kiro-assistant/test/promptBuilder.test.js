const test = require("node:test");
const assert = require("node:assert/strict");

const { PromptBuilder } = require("../src/core/promptBuilder");
const { MODES } = require("../src/core/modeManager");

test("PromptBuilder builds plan, build, and improve prompts with context", () => {
  const builder = new PromptBuilder();
  const prompts = builder.buildPlanBuildImprove("Add slash commands", {
    workspaceName: "demo",
    memory: [{ key: "style", value: "spec-first" }],
    files: [{ path: "src/extension.js", snippet: "activate()" }]
  }, MODES.SPEC);

  assert.match(prompts.plan, /Goal: Add slash commands/);
  assert.match(prompts.plan, /Start from requirements, design, and tasks/);
  assert.match(prompts.build, /Implement the smallest complete slice first/);
  assert.match(prompts.improve, /Review for regressions/);
});
