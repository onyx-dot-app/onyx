import { defineRule, type ESTree, type Variable } from "@oxlint/plugins";

const effectHooks = new Set(["useEffect", "useLayoutEffect"]);

function enclosingCall(callee: ESTree.Node): ESTree.CallExpression | undefined {
  const parent = callee.parent;
  switch (parent?.type) {
    case "CallExpression":
      return parent.callee === callee ? parent : undefined;
    case "ParenthesizedExpression":
    case "TSAsExpression":
    case "TSSatisfiesExpression":
    case "TSTypeAssertion":
    case "TSNonNullExpression":
    case "TSInstantiationExpression":
      return enclosingCall(parent);
  }
}

function staticName(node: ESTree.Node, computed = false): string | undefined {
  if (!computed && node.type === "Identifier") return node.name;
  if (node.type === "Literal" && typeof node.value === "string") {
    return node.value;
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
    function reportCalls(variable: Variable, namespace: boolean) {
      for (const { identifier } of variable.references) {
        let callee: ESTree.Node = identifier;
        if (namespace) {
          const member = identifier.parent;
          if (
            member.type !== "MemberExpression" ||
            member.object !== identifier ||
            !effectHooks.has(staticName(member.property, member.computed) ?? "")
          )
            continue;
          callee = member;
        }
        const call = enclosingCall(callee);
        if (call) context.report({ node: call, messageId: "effect" });
      }
    }

    return {
      ImportDeclaration(node) {
        if (node.source.value !== "react" || node.importKind === "type") return;

        for (const specifier of node.specifiers) {
          const imported =
            specifier.type === "ImportSpecifier"
              ? staticName(specifier.imported)
              : "default";
          if (
            specifier.type === "ImportSpecifier" &&
            specifier.importKind === "type"
          )
            continue;
          const namespace = imported === "default";
          if (!namespace && !effectHooks.has(imported ?? "")) continue;

          for (const variable of context.sourceCode.getDeclaredVariables(
            specifier
          )) {
            reportCalls(variable, namespace);
          }
        }
      },
      VariableDeclarator(node) {
        const { sourceCode } = context;
        const { id, init } = node;
        if (init?.type !== "CallExpression") return;
        const [module] = init.arguments;
        if (module?.type !== "Literal" || module.value !== "react") return;

        const { callee } = init;
        const loader =
          callee.type === "Identifier" && callee.name === "require"
            ? callee
            : callee.type === "MemberExpression" &&
                callee.object.type === "Identifier" &&
                callee.object.name === "jest" &&
                staticName(callee.property, callee.computed) === "requireActual"
              ? callee.object
              : undefined;
        if (!loader) return;

        let scope = sourceCode.getScope(loader);
        while (scope.upper && !scope.set.has(loader.name)) scope = scope.upper;
        if (scope.set.get(loader.name)?.defs.length) return;

        for (const variable of sourceCode.getDeclaredVariables(node)) {
          if (id.type === "Identifier") {
            reportCalls(variable, true);
          } else if (
            id.type === "ObjectPattern" &&
            id.properties.some(
              (property) =>
                property.type === "Property" &&
                property.value.type === "Identifier" &&
                property.value.name === variable.name &&
                effectHooks.has(
                  staticName(property.key, property.computed) ?? ""
                )
            )
          ) {
            reportCalls(variable, false);
          }
        }
      },
    };
  },
});
