function parseChecklist(markdown, source) {
  const items = [];
  const lines = markdown.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const match = line.match(/^\s*-\s*\[( |x|X)\]\s+(.*)$/);
    if (!match) {
      continue;
    }

    items.push({
      source,
      line: index + 1,
      checked: match[1].toLowerCase() === "x",
      text: match[2].trim()
    });
  }

  return items;
}

function parseInlineTasks(text, source) {
  const items = [];
  const lines = text.split(/\r?\n/);

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const match = line.match(/\b(TODO|FIXME|XXX)\b[:\s-]*(.*)$/);
    if (!match) {
      continue;
    }

    items.push({
      source,
      line: index + 1,
      kind: match[1],
      text: match[2].trim()
    });
  }

  return items;
}

module.exports = {
  parseChecklist,
  parseInlineTasks
};
