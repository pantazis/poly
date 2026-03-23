const test = require("node:test");
const assert = require("node:assert/strict");

const { CommandRouter } = require("../src/core/commandRouter");
const { MODES } = require("../src/core/modeManager");

function createServices() {
  const state = { mode: MODES.SPEC };
  return {
    modeManager: {
      getMode() {
        return state.mode;
      },
      async setMode(mode) {
        state.mode = mode;
      }
    },
    specBootstrap: {
      async createSpec() {}
    },
    memoryStore: {
      async set() {}
    },
    taskDetector: {
      async scanWorkspace() {
        return {
          checklistItems: [{ checked: false }],
          inlineTasks: [{ kind: "TODO" }]
        };
      }
    },
    contextCollector: {
      async collect() {
        return {
          workspaceName: "demo",
          memory: [],
          files: []
        };
      }
    },
    promptBuilder: {
      buildPlanBuildImprove() {
        return {
          plan: "plan prompt",
          build: "build prompt",
          improve: "improve prompt"
        };
      }
    }
  };
}

test("CommandRouter switches modes via /mode", async () => {
  const router = new CommandRouter(createServices());
  const result = await router.run("/mode vibe");
  assert.equal(result.message, "Mode set to vibe");
});

test("CommandRouter returns prompt payloads", async () => {
  const router = new CommandRouter(createServices());
  const result = await router.run("/plan add memory");
  assert.equal(result.kind, "prompt");
  assert.equal(result.body, "plan prompt");
});
