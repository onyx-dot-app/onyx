import { defineRule, type ESTree } from "@oxlint/plugins";

import { callPath, isFunction } from "../shared/test-syntax.ts";

const timers = new Set(["requestAnimationFrame", "setTimeout"]);
const globals = new Set(["global", "globalThis", "self", "window"]);

function isTimer(callee: ESTree.Node): boolean {
  const path = callPath(callee);
  const name =
    path.length === 2 && globals.has(path[0] ?? "")
      ? path[1]
      : path.length === 1
        ? path[0]
        : undefined;
  return name !== undefined && timers.has(name);
}

function inPromiseExecutor(node: ESTree.Node): boolean {
  for (let parent = node.parent; parent; parent = parent.parent) {
    const promise = parent.parent;
    if (
      isFunction(parent) &&
      promise?.type === "NewExpression" &&
      callPath(promise.callee).join(".") === "Promise" &&
      promise.arguments[0] === parent
    ) {
      return true;
    }
  }
  return false;
}

export const noRealTimeWaitInTestsRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Require tests to wait for a specific state, not for time or a frame to pass.",
    },
    messages: {
      wait: "Wait for a specific state or event, or drive the fake timer.",
    },
  },
  createOnce(context) {
    return {
      MemberExpression(node) {
        if (callPath(node).at(-1) === "waitForTimeout") {
          context.report({ node: node.property, messageId: "wait" });
        }
      },
      CallExpression(node) {
        if (isTimer(node.callee) && inPromiseExecutor(node)) {
          context.report({ node: node.callee, messageId: "wait" });
        }
      },
    };
  },
});
