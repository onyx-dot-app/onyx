import { defineRule } from "@oxlint/plugins";

const effectHooks = new Set(["useEffect", "useLayoutEffect"]);

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
        const { callee } = node;
        const name =
          callee.type === "Identifier"
            ? callee.name
            : callee.type === "MemberExpression" &&
                !callee.computed &&
                callee.property.type === "Identifier"
              ? callee.property.name
              : undefined;
        if (name && effectHooks.has(name)) {
          context.report({ node, messageId: "effect" });
        }
      },
    };
  },
});
