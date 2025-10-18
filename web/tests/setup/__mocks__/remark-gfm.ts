/**
 * Mock for remark-gfm
 *
 * Why this mock exists:
 * remark-gfm (GitHub Flavored Markdown plugin) uses ESM which Jest cannot parse.
 * It's a dependency of react-markdown that components import.
 *
 * Limitation:
 * GFM features (tables, strikethrough, etc.) are not processed in tests.
 *
 * Usage:
 * Automatically applied via jest.config.js moduleNameMapper.
 */

// No-op plugin that does nothing but allows imports to succeed
export default function remarkGfm() {
  return function () {};
}
