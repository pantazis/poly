const test = require("node:test");
const assert = require("node:assert/strict");

const { ModeManager, MODES } = require("../src/core/modeManager");

function createState() {
  const store = new Map();
  return {
    get(key, fallback) {
      return store.has(key) ? store.get(key) : fallback;
    },
    async update(key, value) {
      store.set(key, value);
    }
  };
}

test("ModeManager defaults to spec mode and toggles", async () => {
  const manager = new ModeManager(createState());
  assert.equal(manager.getMode(), MODES.SPEC);
  assert.equal(await manager.toggleMode(), MODES.VIBE);
  assert.equal(manager.getMode(), MODES.VIBE);
});

test("ModeManager rejects unsupported modes", async () => {
  const manager = new ModeManager(createState());
  await assert.rejects(() => manager.setMode("invalid"), /Unsupported mode/);
});
