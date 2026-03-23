const fs = require("fs/promises");
const path = require("path");

const { parseChecklist, parseInlineTasks } = require("./taskParser");

class TaskDetector {
  constructor(workspaceRoot) {
    this.workspaceRoot = workspaceRoot;
  }

  async scanWorkspace() {
    const files = await walk(this.workspaceRoot);
    const markdownFiles = files.filter((filePath) => filePath.endsWith(".md"));
    const codeFiles = files.filter((filePath) => /\.(js|ts|py|md|tsx|jsx)$/.test(filePath));

    const checklistItems = [];
    const inlineTasks = [];

    for (const filePath of markdownFiles) {
      const content = await fs.readFile(filePath, "utf8");
      checklistItems.push(...parseChecklist(content, filePath));
    }

    for (const filePath of codeFiles) {
      const content = await fs.readFile(filePath, "utf8");
      inlineTasks.push(...parseInlineTasks(content, filePath));
    }

    return {
      checklistItems,
      inlineTasks
    };
  }

  renderReport(findings) {
    const checklist = findings.checklistItems
      .map((item) => `<li>${escapeHtml(path.relative(this.workspaceRoot, item.source))}:${item.line} [${item.checked ? "x" : " "}] ${escapeHtml(item.text)}</li>`)
      .join("");
    const inlineTasks = findings.inlineTasks
      .map((item) => `<li>${escapeHtml(path.relative(this.workspaceRoot, item.source))}:${item.line} ${item.kind} ${escapeHtml(item.text)}</li>`)
      .join("");

    return [
      "<html><body>",
      "<h2>Checklist Items</h2>",
      `<ul>${checklist || "<li>No checklist items found</li>"}</ul>`,
      "<h2>Inline Tasks</h2>",
      `<ul>${inlineTasks || "<li>No inline tasks found</li>"}</ul>`,
      "</body></html>"
    ].join("");
  }
}

async function walk(root) {
  const entries = await fs.readdir(root, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    if (entry.name === ".git" || entry.name === "node_modules") {
      continue;
    }

    const fullPath = path.join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...await walk(fullPath));
      continue;
    }

    files.push(fullPath);
  }

  return files;
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

module.exports = {
  TaskDetector
};
