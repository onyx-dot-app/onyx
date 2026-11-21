import DOMPurify from "dompurify";

// A CSS url(), quoted (as the browser writes a style back) or not
const CSS_URL =
  /url\(\s*(?:"((?:[^"\\]|\\.)*)"|'((?:[^'\\]|\\.)*)'|([^"'()\s]*))\s*\)/gi;

/**
 * Whether a CSS value loads from outside the deck: any of its url()s is not
 * an embedded image. A url() that the pattern cannot read counts as outside.
 */
function loadsFromOutside(value: string): boolean {
  const urls = Array.from(
    value.matchAll(CSS_URL),
    (match) => match[1] ?? match[2] ?? match[3] ?? ""
  );
  return (
    urls.length !== (value.match(/url\(/gi)?.length ?? 0) ||
    urls.some((url) => !url.startsWith("data:image/"))
  );
}

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
    for (const element of template.content.querySelectorAll("*")) {
      // Only embedded images load. A link keeps its `href` as is; any other
      // `href` (also SVG's `xlink:href`) must be an embedded image.
      for (const attribute of Array.from(element.attributes)) {
        const name = attribute.localName;
        const loadsUrl =
          name === "src" ||
          name === "srcset" ||
          name === "poster" ||
          (name === "href" && element.localName !== "a");
        if (loadsUrl && !attribute.value.startsWith("data:image/"))
          element.removeAttributeNode(attribute);
      }
    }
    for (const element of template.content.querySelectorAll<HTMLElement>(
      "[style]"
    )) {
      for (const property of Array.from(element.style)) {
        if (loadsFromOutside(element.style.getPropertyValue(property)))
          element.style.removeProperty(property);
      }
    }
    return template.innerHTML;
  });
}
