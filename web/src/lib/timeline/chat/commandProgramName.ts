const SHELL_SCRIPT =
  /^\s*(?:sudo\s+)?(?:\S*\/)?(?:bash|sh|zsh|dash)\s+-l?c\s+(["'])([\s\S]*)\1\s*$/;
/** Commands that run another program, with their options that take a value. */
const PREFIXES = new Map<string, ReadonlySet<string>>([
  [
    "sudo",
    new Set(["-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-T", "-U"]),
  ],
  ["env", new Set(["-u", "-C", "-S"])],
  ["time", new Set(["-f", "-o"])],
  ["nohup", new Set()],
  ["exec", new Set(["-a"])],
  ["command", new Set()],
]);

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
  let valueOptions: ReadonlySet<string> | null = null;
  while (index < tokens.length) {
    const token = tokens[index] ?? "";
    const prefixOptions = PREFIXES.get(token);
    if (prefixOptions) {
      valueOptions = prefixOptions;
    } else if (valueOptions && token.startsWith("-")) {
      if (valueOptions.has(token)) index++;
    } else if (!/^[A-Za-z_][A-Za-z0-9_]*=/.test(token)) {
      break;
    }
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
