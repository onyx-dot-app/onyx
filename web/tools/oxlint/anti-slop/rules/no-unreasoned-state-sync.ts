import { defineRule, type ESTree } from "@oxlint/plugins";

const effectHooks = new Set(["useEffect", "useLayoutEffect"]);

function enclosingCall(callee: ESTree.Node): ESTree.CallExpression | undefined {
  const parent = callee.parent;
  switch (parent?.type) {
    case "CallExpression":
      return parent.callee === callee ? parent : undefined;
    case "TSAsExpression":
    case "TSSatisfiesExpression":
    case "TSTypeAssertion":
    case "TSNonNullExpression":
    case "TSInstantiationExpression":
      return enclosingCall(parent);
  }
}

export const noUnreasonedStateSyncRule = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Require a reason for each React effect.",
    },
    messages: {
      effect:
        "Derive values in render and act in event handlers. If this effect syncs with something outside React, explain what it syncs with using `// oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- <why>`.",
    },
  },
  createOnce(context) {
    return {
      CallExpression(node) {
        let callee = node.callee;
        while (
          callee.type === "TSAsExpression" ||
          callee.type === "TSSatisfiesExpression" ||
          callee.type === "TSTypeAssertion" ||
          callee.type === "TSNonNullExpression" ||
          callee.type === "TSInstantiationExpression"
        ) {
          callee = callee.expression;
        }
        const name =
          callee.type === "Identifier"
            ? callee.name
            : callee.type === "MemberExpression"
              ? callee.computed
                ? callee.property.type === "Literal" && callee.property.value
                : callee.property.type === "Identifier" && callee.property.name
              : undefined;
        if (typeof name === "string" && effectHooks.has(name)) {
          context.report({ node, messageId: "effect" });
        }
      },
      ImportDeclaration(node) {
        if (node.source.value !== "react" || node.importKind === "type") return;

        for (const specifier of node.specifiers) {
          if (
            specifier.type !== "ImportSpecifier" ||
            specifier.importKind === "type" ||
            effectHooks.has(specifier.local.name)
          )
            continue;
          const imported = specifier.imported;
          const name =
            imported.type === "Identifier" ? imported.name : imported.value;
          if (!effectHooks.has(name)) continue;

          for (const variable of context.sourceCode.getDeclaredVariables(
            specifier
          )) {
            for (const { identifier } of variable.references) {
              const call = enclosingCall(identifier);
              if (call) context.report({ node: call, messageId: "effect" });
            }
          }
        }
      },
    };
  },
});
