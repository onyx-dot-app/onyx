import { useMemo } from "react";
import hljs from "highlight.js/lib/core";
import bash from "highlight.js/lib/languages/bash";

function ensureBashHljsRegistered() {
  if (!hljs.listLanguages().includes("bash")) {
    hljs.registerLanguage("bash", bash);
  }
}

export function HighlightedBashCode({ code }: { code: string }) {
  const highlightedHtml = useMemo(() => {
    ensureBashHljsRegistered();
    try {
      return hljs.highlight(code, { language: "bash" }).value;
    } catch {
      return code
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }
  }, [code]);

  return (
    <span
      dangerouslySetInnerHTML={{ __html: highlightedHtml }}
      className="hljs"
    />
  );
}
