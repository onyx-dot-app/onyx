import { defineRule } from "@oxlint/plugins";

import {
  inJestMock,
  testBindings,
  usesFakeTimers,
} from "../shared/test-framework.ts";
import {
  callPath,
  globalPath,
  inPromiseExecutor,
  isPromise,
  staticText,
} from "../shared/test-syntax.ts";

export const noFrameWaitsInTestsRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Disallow waiting for renderer ticks to settle a test.",
    },
    messages: {
      frame: "Wait for the UI state or drive the frame with fake timers.",
    },
  },
  create(context) {
    const bindings = testBindings(context.filename);
    return {
      ImportDeclaration: bindings.ImportDeclaration,
      CallExpression(node) {
        const event = staticText(node.arguments[0]);
        if (
          ((globalPath(node.callee) === "requestAnimationFrame" &&
            !usesFakeTimers(node, bindings, "requestAnimationFrame")) ||
            (callPath(node.callee).at(-1) === "addEventListener" &&
              (event === "animationend" || event === "transitionend"))) &&
          inPromiseExecutor(node) &&
          !inJestMock(node, bindings.jest)
        ) {
          context.report({ node: node.callee, messageId: "frame" });
        }
      },
      NewExpression(node) {
        if (
          isPromise(node) &&
          globalPath(node.arguments[0]) === "requestAnimationFrame" &&
          !usesFakeTimers(node, bindings, "requestAnimationFrame") &&
          !inJestMock(node, bindings.jest)
        ) {
          context.report({ node, messageId: "frame" });
        }
      },
    };
  },
});
