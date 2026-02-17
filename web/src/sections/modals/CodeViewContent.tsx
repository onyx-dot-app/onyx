"use client";

import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import "@/app/app/message/custom-code-styles.css";
import ScrollIndicatorDiv from "@/refresh-components/ScrollIndicatorDiv";

// Common code file extensions mapped to highlight.js language identifiers
const CODE_EXTENSIONS: Record<string, string> = {
  ".py": "python",
  ".js": "javascript",
  ".jsx": "javascript",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".java": "java",
  ".go": "go",
  ".rs": "rust",
  ".rb": "ruby",
  ".php": "php",
  ".c": "c",
  ".cpp": "cpp",
  ".h": "c",
  ".hpp": "cpp",
  ".cs": "csharp",
  ".swift": "swift",
  ".kt": "kotlin",
  ".scala": "scala",
  ".sh": "bash",
  ".bash": "bash",
  ".zsh": "bash",
  ".sql": "sql",
  ".html": "html",
  ".css": "css",
  ".scss": "scss",
  ".json": "json",
  ".yaml": "yaml",
  ".yml": "yaml",
  ".xml": "xml",
  ".toml": "toml",
  ".r": "r",
  ".lua": "lua",
  ".pl": "perl",
  ".ex": "elixir",
  ".exs": "elixir",
  ".erl": "erlang",
  ".hs": "haskell",
  ".ml": "ocaml",
  ".dockerfile": "dockerfile",
};

export function getCodeLanguage(name: string): string | null {
  const lowerName = name.toLowerCase();
  if (lowerName === "dockerfile") return "dockerfile";
  const ext = lowerName.match(/\.[^.]+$/)?.[0];
  return ext ? CODE_EXTENSIONS[ext] ?? null : null;
}

interface CodeViewContentProps {
  fileContent: string;
  language: string;
}

export default function CodeViewContent({
  fileContent,
  language,
}: CodeViewContentProps) {
  return (
    <ScrollIndicatorDiv className="flex-1 min-h-0 p-4" variant="shadow">
      <MinimalMarkdown
        content={`\`\`\`${language}\n${fileContent}\n\`\`\``}
        className="w-full pb-4 h-full break-words"
      />
    </ScrollIndicatorDiv>
  );
}
