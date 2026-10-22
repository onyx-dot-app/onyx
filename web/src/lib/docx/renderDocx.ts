import DOMPurify from "dompurify";

/** Render off-screen so untrusted markup is sanitized before it reaches the page. */
export async function renderDocx(buffer: ArrayBuffer) {
  const { renderAsync } = await import("docx-preview");
  const body = document.createElement("div");
  const styles = document.createElement("div");
  await renderAsync(buffer, body, styles, {
    className: "docx",
    inWrapper: false,
    ignoreWidth: false,
    ignoreHeight: false,
    ignoreFonts: false,
    breakPages: true,
    useBase64URL: true,
    renderHeaders: true,
    renderFooters: true,
    renderFootnotes: true,
    renderEndnotes: true,
  });
  // Allow document links and embedded images, but not executable URLs.
  body.innerHTML = DOMPurify.sanitize(body.innerHTML, {
    ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
  });
  for (const child of Array.from(styles.children)) {
    if (child.tagName !== "STYLE") child.remove();
  }
  return { body, styles };
}
