const fs = require("fs/promises");
const path = require("path");

class MemoryStore {
  constructor(filePath) {
    this.filePath = filePath;
  }

  getFilePath() {
    return this.filePath;
  }

  async load() {
    try {
      const raw = await fs.readFile(this.filePath, "utf8");
      return JSON.parse(raw);
    } catch (error) {
      if (error.code === "ENOENT") {
        return { notes: {} };
      }
      throw error;
    }
  }

  async set(key, value) {
    const memory = await this.load();
    memory.notes[key] = {
      value,
      updatedAt: new Date().toISOString()
    };
    await this.save(memory);
    return memory.notes[key];
  }

  async save(memory) {
    await fs.mkdir(path.dirname(this.filePath), { recursive: true });
    await fs.writeFile(this.filePath, `${JSON.stringify(memory, null, 2)}\n`, "utf8");
  }
}

module.exports = {
  MemoryStore
};
