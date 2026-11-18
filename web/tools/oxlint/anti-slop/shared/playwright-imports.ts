import { readFileSync, realpathSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { parseSync, type Expression, type Program } from "oxc-parser";

function fixturePath(
  inFile: string,
  source: string,
  testsRoot: string
): string | undefined {
  const base = source.startsWith("@tests/")
    ? resolve(testsRoot, source.slice("@tests/".length))
    : /^\.\.?\//u.test(source)
      ? resolve(dirname(inFile), source)
      : undefined;
  if (!base) return undefined;

  const stem = base.replace(/\.[cm]?jsx?$/u, "");
  for (const candidate of [
    base,
    `${stem}.ts`,
    `${stem}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ]) {
    const pathFromTests = relative(testsRoot, candidate);
    if (
      pathFromTests === ".." ||
      pathFromTests.startsWith(`..${sep}`) ||
      isAbsolute(pathFromTests)
    ) {
      continue;
    }
    if (!statSync(candidate, { throwIfNoEntry: false })?.isFile()) continue;
    const realPath = realpathSync(candidate);
    const realRelative = relative(testsRoot, realPath);
    if (
      realRelative !== ".." &&
      !realRelative.startsWith(`..${sep}`) &&
      !isAbsolute(realRelative)
    ) {
      return realPath;
    }
  }
  return undefined;
}

function fixtureBase(expression: Expression): string | undefined {
  if (expression.type === "Identifier") return expression.name;
  if (
    expression.type === "CallExpression" &&
    expression.callee.type === "MemberExpression"
  ) {
    const { object, property, computed } = expression.callee;
    if (
      (!computed &&
        property.type === "Identifier" &&
        property.name === "extend") ||
      (computed && property.type === "Literal" && property.value === "extend")
    ) {
      return fixtureBase(object);
    }
  }
  if (
    expression.type === "TSAsExpression" ||
    expression.type === "TSNonNullExpression" ||
    expression.type === "TSSatisfiesExpression"
  ) {
    return fixtureBase(expression.expression);
  }
  return undefined;
}

function declaredFixtureBase(
  program: Program,
  name: string
): string | undefined {
  for (const statement of program.body) {
    const declaration =
      statement.type === "ExportNamedDeclaration"
        ? statement.declaration
        : statement;
    if (declaration?.type !== "VariableDeclaration") continue;
    for (const { id, init } of declaration.declarations) {
      if (id.type === "Identifier" && id.name === name && init) {
        return fixtureBase(init);
      }
    }
  }
  return undefined;
}

export function isPlaywrightImport(
  filename: string,
  source: string,
  imported: string
): boolean {
  if (source === "@playwright/test") return imported === "test";
  const testsDir = resolve(filename).match(
    /^(.*[/\\]tests)[/\\]e2e[/\\]/u
  )?.[1];
  if (!testsDir) return false;
  const testsRoot = realpathSync(testsDir);
  const visited = new Set<string>();

  function fromModule(
    inFile: string,
    specifier: string,
    exported: string
  ): boolean {
    if (specifier === "@playwright/test") return exported === "test";
    const path = fixturePath(inFile, specifier, testsRoot);
    if (!path) return false;
    const key = `export:${path}:${exported}`;
    if (visited.has(key)) return false;
    visited.add(key);

    const parsed = parseSync(path, readFileSync(path, "utf8"));
    const { staticImports, staticExports } = parsed.module;
    const fromLocal = (local: string): boolean => {
      const localKey = `local:${path}:${local}`;
      if (visited.has(localKey)) return false;
      visited.add(localKey);
      for (const { moduleRequest, entries } of staticImports) {
        const binding = entries.find(
          (entry) => !entry.isType && entry.localName.value === local
        );
        if (!binding) continue;
        const name =
          binding.importName.kind === "Default"
            ? "default"
            : binding.importName.name;
        return name !== null && fromModule(path, moduleRequest.value, name);
      }
      const base = declaredFixtureBase(parsed.program, local);
      return base !== undefined && fromLocal(base);
    };

    const exports = staticExports
      .flatMap(({ entries }) => entries)
      .filter((entry) => !entry.isType);
    const direct = exports.find(
      ({ exportName }) =>
        exportName.name === exported ||
        (exportName.kind === "Default" && exported === "default")
    );
    if (direct) {
      if (direct.moduleRequest) {
        return (
          direct.importName.name !== null &&
          fromModule(path, direct.moduleRequest.value, direct.importName.name)
        );
      }
      return direct.localName.name !== null && fromLocal(direct.localName.name);
    }
    return (
      exported !== "default" &&
      exports.some(
        ({ importName, moduleRequest }) =>
          importName.kind === "AllButDefault" &&
          moduleRequest !== null &&
          fromModule(path, moduleRequest.value, exported)
      )
    );
  }

  return fromModule(filename, source, imported);
}
