const MODES = {
  VIBE: "vibe",
  SPEC: "spec"
};

class ModeManager {
  constructor(state) {
    this.state = state;
  }

  getMode() {
    return this.state.get("kiro.mode", MODES.SPEC);
  }

  async setMode(mode) {
    if (!Object.values(MODES).includes(mode)) {
      throw new Error(`Unsupported mode: ${mode}`);
    }

    await this.state.update("kiro.mode", mode);
    return mode;
  }

  async toggleMode() {
    const nextMode = this.getMode() === MODES.SPEC ? MODES.VIBE : MODES.SPEC;
    await this.setMode(nextMode);
    return nextMode;
  }
}

module.exports = {
  MODES,
  ModeManager
};
