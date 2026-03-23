const test = require("node:test");
const assert = require("node:assert/strict");

const { parseChecklist, parseInlineTasks } = require("../src/core/taskParser");

test("parseChecklist extracts checkbox items", () => {
  const markdown = [
    "- [ ] open item",
    "- [x] closed item",
    "plain text"
  ].join("\n");

  const items = parseChecklist(markdown, "tasks.md");
  assert.equal(items.length, 2);
  assert.deepEqual(items[0], {
    source: "tasks.md",
    line: 1,
    checked: false,
    text: "open item"
  });
});

test("parseInlineTasks extracts TODO and FIXME entries", () => {
  const source = [
    "const a = 1; // TODO wire this up",
    "# FIXME revise parser"
  ].join("\n");

  const items = parseInlineTasks(source, "file.js");
  assert.equal(items.length, 2);
  assert.equal(items[0].kind, "TODO");
  assert.equal(items[1].kind, "FIXME");
});
