const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs/promises");
const os = require("os");
const path = require("path");

const { MemoryStore } = require("../src/core/memoryStore");

test("MemoryStore persists notes to disk", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "kiro-memory-"));
  const store = new MemoryStore(path.join(root, ".kiro", "memory.json"));
  await store.set("architecture", "service-based");

  const saved = JSON.parse(await fs.readFile(store.getFilePath(), "utf8"));
  assert.equal(saved.notes.architecture.value, "service-based");
});
