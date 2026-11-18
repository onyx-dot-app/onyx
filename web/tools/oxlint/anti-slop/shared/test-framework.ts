import type { ESTree } from "@oxlint/plugins";

import { isPlaywrightImport } from "./playwright-imports.ts";
import { callPath, option, staticName, staticText } from "./test-syntax.ts";

export const testHooks = new Set([
  "afterAll",
  "afterEach",
  "beforeAll",
  "beforeEach",
]);
export const disabledTests = new Set(["xdescribe", "xit", "xtest"]);
const jestNames = new Set([
  "describe",
  "it",
  "test",
  ...testHooks,
  ...disabledTests,
]);

export function testBindings(filename: string) {
  const playwright = /(?:^|[/\\])tests[/\\]e2e[/\\]/u.test(filename);
  const tests = new Map(
    [...(playwright ? ["test"] : jestNames)].map((name) => [name, name])
  );
  const jest = new Set(playwright ? [] : ["jest"]);

  const imports = new Map<string, { source: string; imported: string }>();
  const testName = (local: string) => {
    const known = tests.get(local);
    if (known) return known;
    const binding = imports.get(local);
    if (!binding) return undefined;
    imports.delete(local);
    if (isPlaywrightImport(filename, binding.source, binding.imported)) {
      tests.set(local, "test");
      return "test";
    }
    return undefined;
  };

  return {
    playwright,
    testName,
    jest,
    ImportDeclaration(node: ESTree.ImportDeclaration) {
      if (node.importKind === "type") return;
      const source = node.source.value;
      for (const specifier of node.specifiers) {
        const local = specifier.local.name;
        if (specifier.type === "ImportNamespaceSpecifier") continue;
        if (
          specifier.type === "ImportSpecifier" &&
          specifier.importKind === "type"
        )
          continue;
        const name =
          specifier.type === "ImportDefaultSpecifier"
            ? "default"
            : staticName(specifier.imported, false);
        if (name === undefined) continue;

        if (source === "@jest/globals") {
          if (name === "jest") jest.add(local);
          if (jestNames.has(name)) tests.set(local, name);
        }
        if (
          playwright &&
          (source === "@playwright/test" ||
            source.startsWith(".") ||
            source.startsWith("@tests/"))
        ) {
          imports.set(local, { source, imported: name });
        }
      }
    },
    VariableDeclarator(node: ESTree.VariableDeclarator) {
      if (!playwright || node.id.type !== "Identifier") return;
      const [root, member] = callPath(node.init ?? undefined);
      if (root && member === "extend" && testName(root)) {
        tests.set(node.id.name, "test");
      }
    },
  };
}

type Bindings = ReturnType<typeof testBindings>;

function timerToggle(
  node: ESTree.Node,
  jest: ReadonlySet<string>,
  api: string
): boolean | undefined {
  let expression = node.type === "ExpressionStatement" ? node.expression : node;
  while (expression.type === "CallExpression") {
    const [root, method] = callPath(expression.callee);
    if (root && jest.has(root)) {
      if (method === "useRealTimers") return false;
      if (
        method === "useFakeTimers" &&
        expression.callee.type === "MemberExpression"
      ) {
        const methodName = staticName(
          expression.callee.property,
          expression.callee.computed
        );
        if (methodName === method) {
          const exclusions = option(expression.arguments[0], "doNotFake");
          return (
            exclusions?.type !== "ArrayExpression" ||
            !exclusions.elements.some(
              (element) => staticText(element ?? undefined) === api
            )
          );
        }
      }
    }
    if (expression.callee.type !== "MemberExpression") break;
    expression = expression.callee.object;
  }
  return undefined;
}

export function usesFakeTimers(
  node: ESTree.Node,
  bindings: Bindings,
  api: string
): boolean {
  if (bindings.playwright) return false;
  let child = node;
  let inTest = false;
  let beforeEachToggle: boolean | undefined;
  let beforeAllToggle: boolean | undefined;
  let suiteToggle: boolean | undefined;

  const lastToggle = (statements: readonly ESTree.Node[]) => {
    for (const statement of statements.toReversed()) {
      const toggle = timerToggle(statement, bindings.jest, api);
      if (toggle !== undefined) return toggle;
    }
    return undefined;
  };

  for (
    let parent = node.parent;
    parent;
    child = parent, parent = parent.parent
  ) {
    if (
      parent.type === "CallExpression" &&
      parent.arguments.some((arg) => arg === child)
    ) {
      const [root] = callPath(parent.callee);
      const name = root ? bindings.testName(root) : undefined;
      if (name === "test" || name === "it") inTest = true;
    }
    if (parent.type !== "BlockStatement" && parent.type !== "Program") continue;
    if (inTest) {
      suiteToggle ??= lastToggle(parent.body);
      for (const statement of parent.body.toReversed()) {
        if (
          statement.type !== "ExpressionStatement" ||
          statement.expression.type !== "CallExpression"
        )
          continue;
        const [root] = callPath(statement.expression.callee);
        const hook = root ? bindings.testName(root) : undefined;
        if (hook !== "beforeAll" && hook !== "beforeEach") continue;
        const callback = statement.expression.arguments[0];
        if (
          (callback?.type !== "ArrowFunctionExpression" &&
            callback?.type !== "FunctionExpression") ||
          !callback.body
        )
          continue;
        const toggle =
          callback.body.type === "BlockStatement"
            ? lastToggle(callback.body.body)
            : timerToggle(callback.body, bindings.jest, api);
        if (hook === "beforeEach") beforeEachToggle ??= toggle;
        else beforeAllToggle ??= toggle;
      }
      continue;
    }
    const previous = lastToggle(
      parent.body.slice(
        0,
        parent.body.findIndex((statement) => statement === child)
      )
    );
    if (previous !== undefined) return previous;
  }
  return beforeEachToggle ?? beforeAllToggle ?? suiteToggle ?? false;
}

export function inJestMock(
  node: ESTree.Node,
  jest: ReadonlySet<string>
): boolean {
  let child = node;
  for (
    let parent = node.parent;
    parent;
    child = parent, parent = parent.parent
  ) {
    if (parent.type !== "CallExpression" || parent.callee === child) continue;
    const [root] = callPath(parent.callee);
    const method = callPath(parent.callee).at(-1);
    if (
      method?.startsWith("mockImplementation") ||
      method?.startsWith("mockReturnValue") ||
      (root &&
        jest.has(root) &&
        ["fn", "mock", "setSystemTime", "spyOn"].includes(method ?? ""))
    ) {
      return true;
    }
  }
  return false;
}
