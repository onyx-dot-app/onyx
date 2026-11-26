import type { PluggableList } from "unified";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { remarkDetails } from "@/lib/answerText/remarkDetails";
import { remarkGithubAlerts } from "@/lib/answerText/remarkGithubAlerts";

/**
 * The remark plugins of answer markdown, shared by `AnswerMarkdown` and find
 * in chat. Math is `$$…$$` only (see `prepareAnswerMarkdown`).
 */
export const ANSWER_REMARK_PLUGINS: PluggableList = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
  remarkGithubAlerts,
  remarkDetails,
];
