const fs = require("fs/promises");
const path = require("path");

class ContextCollector {
  constructor(workspaceRoot, getConfig) {
    this.workspaceRoot = workspaceRoot;
    this.getConfig = getConfig;
  }

  async collect() {
    const config = this.getConfig();
    const candidates = [
      path.join(this.workspaceRoot, ".kiro", "kiro-assistant-memory.json"),
      path.join(this.workspaceRoot, ".kiro"),
      path.join(this.workspaceRoot, "README.md"),
      path.join(this.workspaceRoot, "package.json"),
      path.join(this.workspaceRoot, "src"),
      path.join(this.workspaceRoot, "tests")
    ];

    const files = [];
    for (const candidate of candidates) {
      const collected = await this.collectCandidate(candidate, config.maxSnippetLength);
      files.push(...collected);
      if (files.length >= config.maxFiles) {
        break;
      }
    }

    const memory = await this.loadMemory();
    return {
      workspaceName: path.basename(this.workspaceRoot),
      files: files.slice(0, config.maxFiles),
      memory
    };
  }

  async collectCandidate(candidate, maxSnippetLength) {
    try {
      const stat = await fs.stat(candidate);
      if (stat.isDirectory()) {
        const entries = await fs.readdir(candidate, { withFileTypes: true });
        const files = [];
        for (const entry of entries) {
          if (entry.isDirectory()) {
            continue;
          }
          const fullPath = path.join(candidate, entry.name);
          files.push(await this.readSnippet(fullPath, maxSnippetLength));
        }
        return files.filter(Boolean);
      }

      const snippet = await this.readSnippet(candidate, maxSnippetLength);
      return snippet ? [snippet] : [];
    } catch (error) {
      if (error.code === "ENOENT") {
        return [];
      }
      throw error;
    }
  }

  async readSnippet(filePath, maxSnippetLength) {
    const content = await fs.readFile(filePath, "utf8");
    return {
      path: path.relative(this.workspaceRoot, filePath),
      snippet: content.slice(0, maxSnippetLength)
    };
  }

  async loadMemory() {
    const memoryPath = path.join(this.workspaceRoot, ".kiro", "kiro-assistant-memory.json");
    try {
      const raw = await fs.readFile(memoryPath, "utf8");
      const parsed = JSON.parse(raw);
      return Object.entries(parsed.notes || {}).map(([key, entry]) => ({
        key,
        value: entry.value
      }));
    } catch (error) {
      if (error.code === "ENOENT") {
        return [];
      }
      throw error;
    }
  }
}

module.exports = {
  ContextCollector
};
