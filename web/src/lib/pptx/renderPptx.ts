import DOMPurify from "dompurify";

// A CSS url() that loads from outside the deck, such as a linked image
const EXTERNAL_CSS_URL = /url\(\s*(['"]?)(?!data:image\/)[^)]*\1\s*\)/i;

/**
 * Parses a PowerPoint deck into one markup string per slide, each a box at
 * the deck's own slide size. The markup is sanitized: it runs no script and
 * loads nothing from outside the deck, so a slide shows only what the file
 * holds. Render each slide in a shadow root, so its styles stay inside it.
 */
export async function renderPptx(bytes: ArrayBuffer): Promise<string[]> {
  const { pptxToHtml } = await import("@jvmr/pptx-to-html");
  const slides = await pptxToHtml(bytes);
  return slides.map((html) => {
    const template = document.createElement("template");
    template.innerHTML = DOMPurify.sanitize(html, {
      ALLOWED_URI_REGEXP: /^(?:https?|mailto):/i,
    });
    for (const element of template.content.querySelectorAll("style"))
      element.remove();
    for (const element of template.content.querySelectorAll("[src]")) {
      if (!element.getAttribute("src")?.startsWith("data:image/"))
        element.removeAttribute("src");
    }
    for (const element of template.content.querySelectorAll<HTMLElement>(
      "[style]"
    )) {
      for (const property of Array.from(element.style)) {
        if (EXTERNAL_CSS_URL.test(element.style.getPropertyValue(property)))
          element.style.removeProperty(property);
      }
    }
    return template.innerHTML;
  });
}
