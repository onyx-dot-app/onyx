import { defineRule, type ESTree } from "@oxlint/plugins";

import { callPath, isFunction } from "../shared/test-syntax.ts";

const jestHooks = new Set(["afterAll", "afterEach", "beforeAll", "beforeEach"]);

/** A test option that raises the time or attempts a test gets. Zero retries is stricter, so it passes. */
function raisesLimit(options: ESTree.Node | undefined): boolean {
  if (options?.type !== "ObjectExpression") return false;
  return options.properties.some((property) => {
    if (property.type !== "Property") return false;
    const [key] = callPath(property.key);
    if (key === "timeout") return true;
    const { value } = property;
    return (
      key === "retries" && !(value.type === "Literal" && value.value === 0)
    );
  });
}

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
  createOnce(context) {
    return {
      CallExpression(node) {
        const path = callPath(node.callee);
        const [root] = path;
        const method = path.at(-1);
        const [first, second, third] = node.arguments;
        if (
          (root === "test" && method === "setTimeout") ||
          (root === "test" && method === "configure" && raisesLimit(first)) ||
          (root === "jest" &&
            (method === "setTimeout" || method === "retryTimes")) ||
          (jestHooks.has(root ?? "") && second !== undefined) ||
          // Jest it(name, fn, timeout), or Playwright test.step(name, fn, options).
          // A Playwright test(name, details, body) passes its details second.
          ((root === "it" || root === "test") &&
            third !== undefined &&
            second?.type !== "ObjectExpression" &&
            !isFunction(third) &&
            (third.type !== "ObjectExpression" || raisesLimit(third)))
        ) {
          context.report({ node, messageId: "timeout" });
        }
      },
    };
  },
});
