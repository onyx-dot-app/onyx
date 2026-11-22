/** The SKILL.md text that the Contents tab shows and edits: a frontmatter
 * with the name and description, then the instructions. */
export function composeSkillMarkdown(skill: {
  name: string;
  description: string;
  instructions: string;
}): string {
  return [
    "---",
    `name: ${JSON.stringify(skill.name)}`,
    `description: ${JSON.stringify(skill.description)}`,
    "---",
    "",
    skill.instructions,
  ].join("\n");
}

export type ParsedSkillMarkdown =
  | { ok: true; name: string; description: string; instructions: string }
  | { ok: false; error: "frontmatter" | "description" };

function scalarValue(raw: string): string {
  const value = raw.trim();
  if (value.startsWith('"')) {
    try {
      const parsed: unknown = JSON.parse(value);
      if (typeof parsed === "string") return parsed;
    } catch {
      return value;
    }
  }
  if (value.startsWith("'") && value.endsWith("'") && value.length >= 2)
    return value.slice(1, -1).replaceAll("''", "'");
  return value;
}

/** A `|` or `>` block: the indented lines after the key. `|` keeps the line
 * breaks, `>` folds them into spaces; a `-` drops the final line break. */
function blockValue(indicator: string, lines: readonly string[]): string {
  const indents = lines
    .filter((line) => line.trim() !== "")
    .map((line) => line.length - line.trimStart().length);
  const indent = indents.length > 0 ? Math.min(...indents) : 0;
  const body = lines.map((line) => line.slice(indent));
  const text = indicator.startsWith(">")
    ? body.join(" ").replace(/\s+/g, " ")
    : body.join("\n");
  return indicator.endsWith("-") ? text.trimEnd() : `${text.trimEnd()}\n`;
}

function frontmatterFields(block: string): Map<string, string> {
  const fields = new Map<string, string>();
  const lines = block.split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    const field = /^([A-Za-z][\w-]*):(.*)$/.exec(lines[index] ?? "");
    if (!field?.[1] || field[2] === undefined) continue;
    const raw = field[2].trim();
    if (/^[|>][+-]?$/.test(raw)) {
      const nested: string[] = [];
      while (
        index + 1 < lines.length &&
        /^(\s|$)/.test(lines[index + 1] ?? "")
      ) {
        index += 1;
        nested.push(lines[index] ?? "");
      }
      fields.set(field[1], blockValue(raw, nested));
    } else {
      fields.set(field[1], scalarValue(raw));
    }
  }
  return fields;
}

/** Reads the name, description and instructions back from the edited text.
 * The instructions keep their indentation; only blank lines before them and
 * trailing space are dropped. */
export function parseSkillMarkdown(text: string): ParsedSkillMarkdown {
  const match = /^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)([\s\S]*)$/.exec(text);
  if (!match) return { ok: false, error: "frontmatter" };
  const fields = frontmatterFields(match[1] ?? "");
  const description = fields.get("description")?.trim() ?? "";
  if (!description) return { ok: false, error: "description" };
  return {
    ok: true,
    name: fields.get("name")?.trim() ?? "",
    description,
    instructions: (match[2] ?? "").replace(/^(\s*\r?\n)+/, "").trimEnd(),
  };
}
