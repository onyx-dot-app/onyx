import DOMPurify from "dompurify";

// docx-preview renders document-controlled content into the DOM via a few
// HTML/href sinks, so we re-sanitize its output. `data:` stays allowed because
// images are base64 data URLs (useBase64URL); other non-http(s)/mailto schemes
// (e.g. javascript:) are dropped.
export function sanitizeDocxHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_URI_REGEXP: /^(?:https?|mailto|data):/i,
  });
}
