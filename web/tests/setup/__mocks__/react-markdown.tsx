/**
 * Mock for react-markdown
 *
 * Why this mock exists:
 * react-markdown uses ESM (ECMAScript Modules) which Jest cannot parse by default.
 * Components like Field.tsx import react-markdown, which would cause test failures.
 *
 * Limitation:
 * Markdown is NOT actually rendered/parsed in tests - content is displayed as plain text.
 * If you need to test actual markdown rendering, you'll need to configure Jest for ESM.
 *
 * Usage:
 * Automatically applied via jest.config.js moduleNameMapper.
 */
import React from "react";

// Simple mock that renders markdown content as plain text
const ReactMarkdown = ({ children }: { children: string }) => {
  return <div>{children}</div>;
};

export default ReactMarkdown;
