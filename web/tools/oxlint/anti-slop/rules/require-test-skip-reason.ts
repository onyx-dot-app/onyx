import { defineRule, type ESTree } from "@oxlint/plugins";

import { callPath, staticText } from "../shared/test-syntax.ts";

const testRoots = new Set(["describe", "it", "test"]);
const disabledTests = new Set(["xdescribe", "xit", "xtest"]);
const issueUrl =
  /https:\/\/(?:github\.com\/[\w.-]+\/[\w.-]+\/issues\/\d+|linear\.app\/[\w-]+\/issue\/[\w-]+)(?=[/\s)]|$)/u;

/** A conditional Playwright skip, `test.skip(condition, "reason")`, explains itself in its second argument. */
function hasReason(node: ESTree.Node | undefined): boolean {
  return Boolean(
    staticText(node)?.trim() ||
    (node?.type === "TemplateLiteral" &&
      node.quasis.some((part) => part.value.cooked?.trim()))
  );
}

export const requireTestSkipReasonRule = defineRule({
  meta: {
    type: "problem",
    docs: { description: "Require a reason to skip a test." },
    messages: {
      reason:
        "Give a conditional skip a reason in its second argument. Put `// Skip: <reason> <issue URL>` directly above a disabled test.",
    },
  },
  createOnce(context) {
    return {
      CallExpression(node) {
        const path = callPath(node.callee);
        const [root] = path;
        const method = path.at(-1);
        const skips =
          (root !== undefined &&
            testRoots.has(root) &&
            (method === "skip" || method === "fixme")) ||
          (path.length === 1 && disabledTests.has(root ?? ""));
        if (!skips || hasReason(node.arguments[1])) return;

        let statement: ESTree.Node = node;
        while (
          statement.parent &&
          statement.parent.type !== "Program" &&
          statement.parent.type !== "BlockStatement"
        ) {
          statement = statement.parent;
        }
        const comment = context.sourceCode.getCommentsBefore(statement).at(-1);
        const note = comment?.value.trim().match(/^Skip:\s*(.+)$/u)?.[1];
        if (
          note &&
          comment?.loc.end.line === statement.loc.start.line - 1 &&
          issueUrl.test(note) &&
          /\w/u.test(note.replace(issueUrl, ""))
        )
          return;

        context.report({ node, messageId: "reason" });
      },
    };
  },
});
