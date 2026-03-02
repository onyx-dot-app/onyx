/**
 * Sentence detection for streaming TTS using 'sbd' library.
 */

import sbd from "sbd";

/**
 * Split text into sentences. Returns complete sentences and remaining buffer.
 */
export function detectSentences(
  text: string,
  isComplete: boolean = false
): { sentences: string[]; buffer: string } {
  const sentences = sbd.sentences(text, {
    newline_boundaries: true,
    html_boundaries: false,
    sanitize: false,
  });

  if (sentences.length === 0) {
    return { sentences: [], buffer: text };
  }

  // Check if text ends with sentence-ending punctuation
  const endsWithPunctuation = /[.!?]["']?\s*$/.test(text.trim());

  if (isComplete || endsWithPunctuation) {
    // All sentences are complete
    return { sentences: sentences.map((s) => s.trim()), buffer: "" };
  }

  // Last sentence might be incomplete - keep it in buffer
  const complete = sentences.slice(0, -1).map((s) => s.trim());
  const buffer = sentences[sentences.length - 1] ?? "";

  return { sentences: complete, buffer };
}
