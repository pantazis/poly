const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("fs/promises");
const os = require("os");
const path = require("path");

const { SpecBootstrap, slugify } = require("../src/core/specBootstrap");

test("slugify normalizes spec names", () => {
  assert.equal(slugify("VS Code Extension"), "vs-code-extension");
});

test("SpecBootstrap creates the standard Kiro files", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "kiro-spec-"));
  const bootstrap = new SpecBootstrap(root);
  const files = await bootstrap.createSpec("VS Code Extension");

  const requirements = await fs.readFile(files.requirements, "utf8");
  const design = await fs.readFile(files.design, "utf8");
  const tasks = await fs.readFile(files.tasks, "utf8");

  assert.match(requirements, /Requirements Document/);
  assert.match(design, /Design Document/);
  assert.match(tasks, /Implementation Plan/);
});
