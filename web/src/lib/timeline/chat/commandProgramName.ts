const SHELL_SCRIPT =
  /^\s*(?:sudo\s+)?(?:\S*\/)?(?:bash|sh|zsh|dash)\s+-l?c\s+(["'])([\s\S]*)\1\s*$/;
const PREFIXES = new Set(["sudo", "env", "time", "nohup", "exec", "command"]);

/** The program a shell command runs, such as `npm` for `cd web && npm test`. */
export function commandProgramName(command: string): string | null {
  const script = command.match(SHELL_SCRIPT)?.[2];
  if (script) return commandProgramName(script);
  const segment = command
    .split(/&&|\|\||;|\|/)
    .map((part) => part.trim())
    .find((part) => part && !/^cd(\s|$)/.test(part));
  if (!segment) return null;
  const tokens = segment.split(/\s+/);
  let index = 0;
  while (
    index < tokens.length &&
    (/^[A-Za-z_][A-Za-z0-9_]*=/.test(tokens[index] ?? "") ||
      PREFIXES.has(tokens[index] ?? ""))
  ) {
    index++;
  }
  const program = tokens[index];
  if (!program) return null;
  const name =
    program
      .replace(/^["']|["']$/g, "")
      .split("/")
      .pop() ?? "";
  return /^[\w.+-]+$/.test(name) ? name : null;
}
