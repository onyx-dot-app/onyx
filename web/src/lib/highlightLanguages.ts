import { all } from "lowlight";
import abap from "highlightjs-sap-abap";

/**
 * Syntax-highlighting grammars passed to rehype-highlight's `languages` option.
 *
 * lowlight's `all` bundle covers every grammar shipped with highlight.js (~190
 * languages). Anything not in highlight.js core — e.g. ABAP — must be registered
 * here from its own third-party grammar package.
 */
export const highlightLanguages = { ...all, abap };
