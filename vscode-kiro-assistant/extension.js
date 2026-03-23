const path = require("path");
const vscode = require("vscode");

const { ModeManager, MODES } = require("./src/core/modeManager");
const { MemoryStore } = require("./src/core/memoryStore");
const { SpecBootstrap } = require("./src/core/specBootstrap");
const { TaskDetector } = require("./src/core/taskDetector");
const { PromptBuilder } = require("./src/core/promptBuilder");
const { CommandRouter } = require("./src/core/commandRouter");
const { ContextCollector } = require("./src/core/contextCollector");

function getWorkspaceRoot() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder ? folder.uri.fsPath : null;
}

function createServices(context) {
  const workspaceRoot = getWorkspaceRoot();
  if (!workspaceRoot) {
    return null;
  }

  const modeManager = new ModeManager(context.workspaceState);
  const memoryStore = new MemoryStore(path.join(workspaceRoot, ".kiro", "kiro-assistant-memory.json"));
  const specBootstrap = new SpecBootstrap(workspaceRoot);
  const taskDetector = new TaskDetector(workspaceRoot);
  const promptBuilder = new PromptBuilder();
  const contextCollector = new ContextCollector(workspaceRoot, () => ({
    maxFiles: vscode.workspace.getConfiguration().get("kiroAssistant.maxContextFiles", 6),
    maxSnippetLength: vscode.workspace.getConfiguration().get("kiroAssistant.maxSnippetLength", 1200)
  }));
  const router = new CommandRouter({
    modeManager,
    memoryStore,
    specBootstrap,
    taskDetector,
    promptBuilder,
    contextCollector
  });

  return {
    modeManager,
    memoryStore,
    specBootstrap,
    taskDetector,
    contextCollector,
    promptBuilder,
    router
  };
}

function activate(context) {
  const services = createServices(context);
  if (!services) {
    vscode.window.showWarningMessage("Kiro Assistant needs an open workspace folder.");
    return;
  }

  const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  const refreshStatusBar = () => {
    const mode = services.modeManager.getMode();
    statusBar.text = `$(hubot) Kiro ${mode === MODES.SPEC ? "Spec" : "Vibe"}`;
    statusBar.command = "kiroAssistant.toggleMode";
    statusBar.tooltip = "Toggle between Spec mode and Vibe mode";
    statusBar.show();
  };

  refreshStatusBar();
  context.subscriptions.push(statusBar);

  context.subscriptions.push(
    vscode.commands.registerCommand("kiroAssistant.toggleMode", async () => {
      const nextMode = await services.modeManager.toggleMode();
      refreshStatusBar();
      vscode.window.showInformationMessage(`Kiro Assistant mode: ${nextMode}`);
    }),
    vscode.commands.registerCommand("kiroAssistant.bootstrapSpec", async () => {
      const specName = await vscode.window.showInputBox({
        prompt: "Spec name",
        placeHolder: "ex: vscode-kiro-extension"
      });
      if (!specName) {
        return;
      }

      const specFiles = await services.specBootstrap.createSpec(specName);
      const items = Object.entries(specFiles).map(([name, filePath]) => `${name}: ${path.relative(getWorkspaceRoot(), filePath)}`);
      vscode.window.showInformationMessage(`Created spec files\n${items.join("\n")}`);
    }),
    vscode.commands.registerCommand("kiroAssistant.scanTasks", async () => {
      const findings = await services.taskDetector.scanWorkspace();
      const openChecklistCount = findings.checklistItems.filter((item) => !item.checked).length;
      const todoCount = findings.inlineTasks.length;
      vscode.window.showInformationMessage(`Found ${openChecklistCount} open checklist items and ${todoCount} inline tasks.`);
      const panel = vscode.window.createWebviewPanel("kiroTasks", "Kiro Task Scan", vscode.ViewColumn.Beside, {});
      panel.webview.html = services.taskDetector.renderReport(findings);
    }),
    vscode.commands.registerCommand("kiroAssistant.planBuildImprove", async () => {
      const goal = await vscode.window.showInputBox({
        prompt: "Goal for the Plan -> Build -> Improve loop"
      });
      if (!goal) {
        return;
      }

      const contextBundle = await services.contextCollector.collect();
      const prompts = services.promptBuilder.buildPlanBuildImprove(goal, contextBundle, services.modeManager.getMode());
      const panel = vscode.window.createWebviewPanel("kiroPrompts", "Plan Build Improve", vscode.ViewColumn.Beside, {});
      panel.webview.html = [
        "<html><body>",
        `<h2>Plan</h2><pre>${escapeHtml(prompts.plan)}</pre>`,
        `<h2>Build</h2><pre>${escapeHtml(prompts.build)}</pre>`,
        `<h2>Improve</h2><pre>${escapeHtml(prompts.improve)}</pre>`,
        "</body></html>"
      ].join("");
    }),
    vscode.commands.registerCommand("kiroAssistant.saveProjectMemory", async () => {
      const key = await vscode.window.showInputBox({ prompt: "Memory key" });
      if (!key) {
        return;
      }

      const value = await vscode.window.showInputBox({ prompt: "Memory value" });
      if (!value) {
        return;
      }

      await services.memoryStore.set(key, value);
      vscode.window.showInformationMessage(`Saved memory: ${key}`);
    }),
    vscode.commands.registerCommand("kiroAssistant.openProjectMemory", async () => {
      const uri = vscode.Uri.file(services.memoryStore.getFilePath());
      const document = await vscode.workspace.openTextDocument(uri);
      await vscode.window.showTextDocument(document);
    }),
    vscode.commands.registerCommand("kiroAssistant.runSlashCommand", async () => {
      const input = await vscode.window.showInputBox({
        prompt: "Slash command",
        placeHolder: "/spec feature-name"
      });
      if (!input) {
        return;
      }

      const result = await services.router.run(input);
      if (result.kind === "prompt") {
        const panel = vscode.window.createWebviewPanel("kiroSlashCommand", result.title, vscode.ViewColumn.Beside, {});
        panel.webview.html = `<html><body><pre>${escapeHtml(result.body)}</pre></body></html>`;
        vscode.window.showInformationMessage(result.message);
        return;
      }

      vscode.window.showInformationMessage(result.message);
    })
  );
}

function deactivate() {}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

module.exports = {
  activate,
  deactivate
};
