import { defineRule } from "@oxlint/plugins";

import { testBindings, testHooks } from "../shared/test-framework.ts";
import { callPath, option } from "../shared/test-syntax.ts";

export const noTestTimeoutOverrideRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Keep test timeouts and retries at the project level.",
    },
    messages: {
      timeout:
        "Use the project timeout and retry policy. Wait for the state needed by the test.",
    },
  },
  create(context) {
    const bindings = testBindings(context.filename);
    return {
      ImportDeclaration: bindings.ImportDeclaration,
      VariableDeclarator: bindings.VariableDeclarator,
      CallExpression(node) {
        const parts = callPath(node.callee);
        const [root, firstMember] = parts;
        if (!root) return;
        const method = parts.at(-1);
        if (
          bindings.playwright &&
          method !== "setTimeout" &&
          method !== "configure"
        )
          return;
        const name = bindings.testName(root);

        const timeoutSetter =
          method === "setTimeout" &&
          (bindings.jest.has(root) ||
            (bindings.playwright &&
              (root === "testInfo" ||
                (name && (parts.length === 2 || firstMember === "info")))));
        const playwrightConfig =
          bindings.playwright &&
          name &&
          firstMember === "describe" &&
          method === "configure" &&
          (option(node.arguments[0], "timeout") ||
            option(node.arguments[0], "retries"));
        const jestTimeout =
          !bindings.playwright &&
          name &&
          name !== "describe" &&
          (method !== "each" || node.callee.type !== "MemberExpression") &&
          method !== "todo" &&
          node.arguments.length > (testHooks.has(name) ? 1 : 2);
        const retries = bindings.jest.has(root) && method === "retryTimes";

        if (timeoutSetter || playwrightConfig || jestTimeout || retries) {
          context.report({ node, messageId: "timeout" });
        }
      },
    };
  },
});
