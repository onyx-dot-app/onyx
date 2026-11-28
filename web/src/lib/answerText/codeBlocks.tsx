"use client";

import { createContext, useContext } from "react";
import type { ExtraProps } from "react-markdown";
import type { Element, ElementContent } from "hast";
import { CodeBlockBody } from "@/lib/timeline/components/bodies/CodeBlockBody";
import { parseCodeFence } from "@/lib/answerText/codeFence";

/** The markdown still grows: code blocks keep their last line plain. */
export const StreamingCodeContext = createContext(false);

export function textOf(nodes: ElementContent[]): string {
  return nodes
    .map((node) =>
      node.type === "text"
        ? node.value
        : node.type === "element"
          ? textOf(node.children)
          : ""
    )
    .join("");
}

/** A fenced code block: the `pre` around one `code`. */
export function AnswerCodeBlock({
  node,
}: React.ComponentProps<"pre"> & ExtraProps) {
  const streaming = useContext(StreamingCodeContext);
  const code = node?.children.find(
    (child): child is Element =>
      child.type === "element" && child.tagName === "code"
  );
  const className = code?.properties.className;
  const languageClass = Array.isArray(className)
    ? className.find(
        (name): name is string =>
          typeof name === "string" && name.startsWith("language-")
      )
    : undefined;
  const { language, fileName } = parseCodeFence(
    languageClass?.slice("language-".length),
    code?.data?.meta ?? undefined
  );
  return (
    // not-prose: the answer's typography styles tables, so without it every
    // code line gets a row border, cell padding and the answer's font size.
    <div data-testid="answer-code-block" className="not-prose">
      <CodeBlockBody
        code={code ? textOf(code.children).replace(/\n$/, "") : ""}
        language={language}
        fileName={fileName}
        streaming={streaming}
      />
    </div>
  );
}

/** Inline code. Fenced blocks never reach it: `pre` renders them whole. */
export function InlineCode({
  children,
}: React.ComponentProps<"code"> & ExtraProps) {
  return (
    // dir="ltr": code is always LTR, even inside RTL prose. The dir attribute
    // also bidi-isolates the run from the surrounding text.
    <span
      dir="ltr"
      data-testid="code-block"
      className="font-mono text-text-05 bg-background-tint-00 rounded-sm text-[0.75em] inline whitespace-pre-wrap wrap-break-word py-0.5 px-1"
    >
      {children}
    </span>
  );
}
