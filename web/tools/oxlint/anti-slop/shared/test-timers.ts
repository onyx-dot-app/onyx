import type { ESTree } from "@oxlint/plugins";

import { callPath, globalPath, staticName } from "./test-syntax.ts";

const timerFunctions = new Set(["setImmediate", "setInterval", "setTimeout"]);

export function callbackTimer(
  node: ESTree.Node | undefined
): string | undefined {
  const name = globalPath(node);
  return timerFunctions.has(name) ? name : undefined;
}

export function timerPromises() {
  const timers = new Set<string>();
  const namespaces = new Set<string>();
  return {
    ImportDeclaration(node: ESTree.ImportDeclaration) {
      if (
        !["node:timers/promises", "timers/promises"].includes(node.source.value)
      )
        return;
      for (const specifier of node.specifiers) {
        if (specifier.type !== "ImportSpecifier") {
          namespaces.add(specifier.local.name);
          continue;
        }
        const name = staticName(specifier.imported, false);
        if (name && timerFunctions.has(name)) timers.add(specifier.local.name);
      }
    },
    isTimer(callee: ESTree.Node) {
      const [root, method] = callPath(callee);
      return (
        root !== undefined &&
        (timers.has(root) ||
          (namespaces.has(root) && timerFunctions.has(method ?? "")))
      );
    },
  };
}
