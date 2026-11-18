import { defineRule, type ESTree } from "@oxlint/plugins";

import {
  inJestMock,
  testBindings,
  usesFakeTimers,
} from "../shared/test-framework.ts";
import { globalPath } from "../shared/test-syntax.ts";

const clockApi = new Map([
  ["Date.now", "Date"],
  ["performance.now", "performance"],
  ["process.hrtime", "hrtime"],
  ["process.hrtime.bigint", "hrtime"],
]);

export const noWallClockInTestsRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description: "Disallow wall-clock reads in test fixtures and assertions.",
    },
    messages: {
      clock:
        "Use fixed dates or a fake clock. Use unique IDs for names and events or counts for assertions.",
    },
  },
  create(context) {
    const bindings = testBindings(context.filename);
    const check = (node: ESTree.Node, api: string) => {
      if (
        usesFakeTimers(node, bindings, api) ||
        inJestMock(node, bindings.jest)
      )
        return;
      context.report({ node, messageId: "clock" });
    };
    return {
      ImportDeclaration: bindings.ImportDeclaration,
      CallExpression(node) {
        const api = clockApi.get(globalPath(node.callee));
        if (api) check(node, api);
      },
      NewExpression(node) {
        if (!node.arguments.length && globalPath(node.callee) === "Date")
          check(node, "Date");
      },
    };
  },
});
