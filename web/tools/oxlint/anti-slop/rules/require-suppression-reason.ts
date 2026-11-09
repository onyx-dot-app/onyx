import { defineRule, type ESTree } from "@oxlint/plugins";

const DIRECTIVE_PATTERN =
  /^\s*\*?\s*(?:(?:oxlint|eslint)-(?:disable|enable)|@ts-(?:expect-error|ignore|nocheck))/u;
const TS_DIRECTIVE_PATTERN =
  /^\s*\*?\s*@ts-(?:expect-error|ignore|nocheck)(?![\w-])(.*)$/su;
const EMPTY_COMMENT_PATTERN = /^[\s*]*$/u;

/** Require every lint or type-checker suppression to say why. */
export const requireSuppressionReasonRule = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description: "Require every lint or type-checker suppression to say why.",
    },
    messages: {
      lintDirective:
        "Say why: end the directive with `-- reason` or put a comment on the line above.",
      tsDirective:
        "Say why: write the reason after the directive or in a comment on the line above.",
    },
  },
  createOnce(context) {
    return {
      Program() {
        const { sourceCode } = context;
        const comments = sourceCode.getAllComments();
        const ownLineCommentsByEndLine = new Map<number, ESTree.Comment>();
        for (const comment of comments) {
          const { line, column } = comment.loc.start;
          if (
            (sourceCode.lines[line - 1] ?? "").slice(0, column).trim() === ""
          ) {
            ownLineCommentsByEndLine.set(comment.loc.end.line, comment);
          }
        }

        const explainedAbove = (directive: ESTree.Comment) => {
          let above = ownLineCommentsByEndLine.get(
            directive.loc.start.line - 1
          );
          while (
            above &&
            (DIRECTIVE_PATTERN.test(above.value) ||
              EMPTY_COMMENT_PATTERN.test(above.value))
          ) {
            above = ownLineCommentsByEndLine.get(above.loc.start.line - 1);
          }
          return above !== undefined;
        };

        for (const directive of sourceCode.getDisableDirectives().directives) {
          if (directive.type === "enable" || directive.justification?.trim())
            continue;
          if (explainedAbove(directive.node)) continue;
          context.report({
            loc: directive.node.loc,
            messageId: "lintDirective",
          });
        }

        for (const comment of comments) {
          const after = TS_DIRECTIVE_PATTERN.exec(comment.value)?.[1];
          if (after === undefined || after.replace(/^[\s:-]+/u, "").trim())
            continue;
          if (explainedAbove(comment)) continue;
          context.report({ loc: comment.loc, messageId: "tsDirective" });
        }
      },
    };
  },
});
