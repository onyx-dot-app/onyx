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

/** For the last block of a streaming answer: hides a tag still arriving. */
export const STREAMING_ANSWER_REMARK_PLUGINS: PluggableList = [
  ...ANSWER_REMARK_PLUGINS.slice(0, -1),
  [remarkDetails, { streaming: true }],
];
