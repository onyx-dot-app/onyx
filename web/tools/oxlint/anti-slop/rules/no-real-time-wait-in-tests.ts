import { defineRule } from "@oxlint/plugins";

import { testBindings, usesFakeTimers } from "../shared/test-framework.ts";
import {
  inPromiseExecutor,
  isPromise,
  staticName,
} from "../shared/test-syntax.ts";
import { callbackTimer, timerPromises } from "../shared/test-timers.ts";

export const noRealTimeWaitInTestsRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Require tests to wait for a specific state or event.",
    },
    messages: {
      wait: "Wait for a specific state or event, or drive the fake timer.",
    },
  },
  create(context) {
    const bindings = testBindings(context.filename);
    const timers = timerPromises();
    return {
      ImportDeclaration(node) {
        bindings.ImportDeclaration(node);
        timers.ImportDeclaration(node);
      },
      MemberExpression(node) {
        if (
          bindings.playwright &&
          staticName(node.property, node.computed) === "waitForTimeout"
        ) {
          context.report({ node: node.property, messageId: "wait" });
        }
      },
      CallExpression(node) {
        const timer = callbackTimer(node.callee);
        if (
          timers.isTimer(node.callee) ||
          (timer &&
            inPromiseExecutor(node) &&
            !usesFakeTimers(node, bindings, timer))
        ) {
          context.report({ node: node.callee, messageId: "wait" });
        }
      },
      NewExpression(node) {
        if (!isPromise(node)) return;
        const timer = callbackTimer(node.arguments[0]);
        if (timer && !usesFakeTimers(node, bindings, timer)) {
          context.report({ node, messageId: "wait" });
        }
      },
    };
  },
});
