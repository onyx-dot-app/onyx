import { defineRule } from "@oxlint/plugins";

import { callPath, staticName, staticText } from "../shared/test-syntax.ts";

export const noNetworkidleInTestsRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Disallow networkidle as a signal of test readiness.",
    },
    messages: {
      idle: "Wait for the relevant locator or response. Network idleness does not signal readiness.",
    },
  },
  createOnce(context) {
    return {
      CallExpression(node) {
        const state = node.arguments[0];
        if (
          state &&
          callPath(node.callee).at(-1) === "waitForLoadState" &&
          staticText(state) === "networkidle"
        ) {
          context.report({ node: state, messageId: "idle" });
        }
      },
      Property(node) {
        if (
          staticName(node.key, node.computed) === "waitUntil" &&
          staticText(node.value) === "networkidle"
        ) {
          context.report({ node: node.value, messageId: "idle" });
        }
      },
    };
  },
});
