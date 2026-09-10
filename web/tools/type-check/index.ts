import { writeFileSync } from "node:fs";
import { availableParallelism } from "node:os";
import { relative, resolve, sep } from "node:path";
import { parseArgs } from "node:util";

import {
  isAsExpression,
  isIdentifier,
  isNonNullExpression,
  isPrivateIdentifier,
  isTypeAssertion,
  SyntaxKind,
} from "typescript-7/unstable/ast";
import type { Node } from "typescript-7/unstable/ast";
import {
  API,
  DiagnosticCategory,
  TypeFlags,
} from "typescript-7/unstable/async";
import type { Checker, Diagnostic, Program } from "typescript-7/unstable/async";

// Type-checks web/ with TypeScript 7 and, from the same program, measures type
// coverage: the share of identifiers whose type is not `any`, with each type
// cast and non-null assertion counted as one more uncovered item.
// `ods type-coverage typescript` groups the per-file counts into directories
// and gates them against .type-coverage-baseline.yaml.

interface FileCount {
  file: string;
  correct: number;
  total: number;
}

const { values } = parseArgs({
  options: { output: { type: "string" } },
});

// `bun run` sets the cwd to web/. File keys are relative to it.
const root = process.cwd();
const configFile = resolve(root, "tsconfig.types.json");

// These files are type-checked but not measured.
// - .next/dev/types exists only after `next dev`, so counting it would change
//   the rows between machines.
// - lib/ holds workspace packages that tsconfig.types.json excludes. Only the
//   files web/ imports are in the program, so the rows would move with imports.
// - Tests and their helpers are not gated.
const UNMEASURED =
  /^(node_modules|\.next|lib|tests)\/|(^|\/)__tests__\/|\.(test|spec)\.tsx?$/;

const api = new API({ cwd: root });
try {
  const snapshot = await api.updateSnapshot({ openProjects: [configFile] });
  const project = snapshot.getProject(configFile);
  if (project === undefined) {
    throw new Error(`${configFile} did not load`);
  }

  const [errors, files] = await Promise.all([
    collectErrors(project.program),
    measure(project.program, project.checker),
  ]);

  if (errors.length > 0) {
    for (const error of errors) {
      console.error(await format(project.program, error));
    }
    const noun = errors.length === 1 ? "error" : "errors";
    console.error(`\nFound ${errors.length} type ${noun}.`);
    process.exitCode = 1;
  } else if (values.output !== undefined) {
    writeFileSync(values.output, `${JSON.stringify({ files }, null, 2)}\n`);
  } else {
    const correct = files.reduce((sum, f) => sum + f.correct, 0);
    const total = files.reduce((sum, f) => sum + f.total, 0);
    const percent = total === 0 ? 100 : (correct / total) * 100;
    console.log(
      `No type errors. Type coverage: ${percent.toFixed(2)}% (${correct} of ${total} identifiers) across ${files.length} files`
    );
  }
} finally {
  await api.close();
}

// The same diagnostics as `tsc --noEmit`.
async function collectErrors(program: Program): Promise<Diagnostic[]> {
  const groups = await Promise.all([
    program.getConfigFileParsingDiagnostics(),
    program.getProgramDiagnostics(),
    program.getSyntacticDiagnostics(),
    program.getGlobalDiagnostics(),
    program.getSemanticDiagnostics(),
  ]);
  const unique = new Map<string, Diagnostic>();
  for (const diagnostic of groups.flat()) {
    if (diagnostic.category !== DiagnosticCategory.Error) continue;
    const key = `${diagnostic.fileName}:${diagnostic.pos}:${diagnostic.code}:${diagnostic.text}`;
    unique.set(key, diagnostic);
  }
  return [...unique.values()];
}

async function format(
  program: Program,
  diagnostic: Diagnostic
): Promise<string> {
  const message = `error TS${diagnostic.code}: ${flatten(diagnostic, 1)}`;
  if (diagnostic.fileName === undefined) {
    return message;
  }
  const file = relative(root, diagnostic.fileName);
  const sourceFile = await program.getSourceFile(diagnostic.fileName);
  if (sourceFile === undefined) {
    return `${file}: ${message}`;
  }
  const { line, character } = sourceFile.getLineAndCharacterOfPosition(
    diagnostic.pos
  );
  return `${file}(${line + 1},${character + 1}): ${message}`;
}

function flatten(diagnostic: Diagnostic, depth: number): string {
  const chain = (diagnostic.messageChain ?? []).map(
    (next) => `\n${"  ".repeat(depth)}${flatten(next, depth + 1)}`
  );
  return [diagnostic.text, ...chain].join("");
}

async function measure(
  program: Program,
  checker: Checker
): Promise<FileCount[]> {
  const pending = (await program.getSourceFileNames()).filter(
    (name) => !UNMEASURED.test(toKey(name)) && !toKey(name).startsWith("..")
  );
  const files: FileCount[] = [];

  async function worker(): Promise<void> {
    for (let name = pending.pop(); name !== undefined; name = pending.pop()) {
      const counts = await countFile(program, checker, name);
      if (counts !== undefined) files.push(counts);
    }
  }
  await Promise.all(Array.from({ length: availableParallelism() }, worker));

  return files.sort((a, b) => (a.file < b.file ? -1 : a.file > b.file ? 1 : 0));
}

async function countFile(
  program: Program,
  checker: Checker,
  name: string
): Promise<FileCount | undefined> {
  const sourceFile = await program.getSourceFile(name);
  if (sourceFile === undefined) {
    return undefined;
  }

  const nodes: Node[] = [];
  let casts = 0;
  const visit = (node: Node): void => {
    if (
      isIdentifier(node) ||
      isPrivateIdentifier(node) ||
      node.kind === SyntaxKind.ThisKeyword
    ) {
      nodes.push(node);
    } else if (isAsExpression(node) || isTypeAssertion(node)) {
      // A cast overrides the checker, so it counts as uncovered. `as const`
      // only narrows literals and `as unknown` only widens, so they are safe.
      const target = node.type.getText(sourceFile);
      if (target !== "const" && target !== "unknown") casts++;
    } else if (isNonNullExpression(node)) {
      // `x!` removes null and undefined without a check, so it is a cast too.
      casts++;
    }
    node.forEachChild(visit);
  };
  sourceFile.forEachChild(visit);

  let correct = 0;
  let total = casts;
  const types =
    nodes.length === 0 ? [] : await checker.getTypeAtLocation(nodes);
  for (const type of types) {
    // Unresolved names, type reference names and JSX tag names get the error
    // type. It is not an `any` the code wrote, so it does not count.
    if (type === undefined || type.isErrorType()) continue;
    total++;
    if ((type.flags & TypeFlags.Any) === 0) correct++;
  }
  return { file: toKey(name), correct, total };
}

function toKey(fileName: string): string {
  return relative(root, fileName).split(sep).join("/");
}
