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
  const paperStyle = document.createElement("style");
  paperStyle.textContent = `
    section.docx {
      background-color: var(--background-neutral-light-00, white);
      border-radius: var(--radius-08, 8px);
      margin-inline: auto;
    }
    section.docx + section.docx { margin-top: 1rem; }
  `;
  styles.append(paperStyle);
  return { body, styles };
}
