import {
  escapeIncompleteBlockMath,
  preprocessLaTeX,
} from "@/app/app/message/codeUtils";

/**
 * Answer markdown as the shared renderer parses it. Math is `$$…$$` only, so
 * "$5 and $10" stays text: `\[…\]` becomes block math and `\(…\)` inline
 * `$$…$$`. A trailing unclosed `$$` is escaped, so streaming LaTeX shows as
 * source until its closing `$$` arrives.
 */
export function prepareAnswerMarkdown(content: string): string {
  return preprocessLaTeX(escapeIncompleteBlockMath(content));
}
