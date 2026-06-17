import DOMPurify from "dompurify";

// docx-preview renders document-controlled content into the DOM via a few
// HTML/href sinks, so we re-sanitize its output. Only http(s)/mailto schemes
// are allowed; everything else (e.g. javascript:) is dropped. Base64 images
// (useBase64URL) still render because DOMPurify's default DATA_URI_TAGS permits
// `data:` in <img src> — but not in <a href>, which is what we want.
export function sanitizeDocxHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
  });
}
