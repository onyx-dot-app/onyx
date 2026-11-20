import { renderPptx } from "@/lib/pptx/renderPptx";
import type { ChatFilePreviewData } from "@/lib/filePreview/loadChatFilePreview";

// The longest side of a thumbnail, as Craft's server-drawn ones
const THUMBNAIL_SIZE = 640;

/**
 * Draws the first page of a PDF, or the first slide of a PowerPoint deck, as
 * an image URL for its file tile. PDF.js loads only for a PDF. A slide shows
 * as an SVG image of its sanitized markup: an SVG image runs no script and
 * loads nothing, so it shows only what the deck holds. Other files, and
 * files over the preview limit, throw.
 */
export async function renderDocumentThumbnail(
  data: ChatFilePreviewData
): Promise<string> {
  if (data.kind === "pdf") {
    const { pdfjs, PDF_DOCUMENT_OPTIONS } =
      await import("@/lib/filePreview/pdfjs");
    const task = pdfjs.getDocument({
      ...PDF_DOCUMENT_OPTIONS,
      data: new Uint8Array(await data.blob.arrayBuffer()),
    });
    try {
      const page = await (await task.promise).getPage(1);
      const { width, height } = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({
        scale: THUMBNAIL_SIZE / Math.max(width, height),
      });
      const canvas = document.createElement("canvas");
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      await page.render({ canvas, viewport }).promise;
      return canvas.toDataURL("image/jpeg", 0.85);
    } finally {
      await task.destroy();
    }
  }
  if (data.kind === "pptx") {
    const [html] = await renderPptx(data.bytes.buffer);
    if (html === undefined) throw new Error("The deck has no slides");
    const template = document.createElement("template");
    template.innerHTML = html;
    const slide = template.content.firstElementChild;
    if (!(slide instanceof HTMLElement))
      throw new Error("The slide is malformed");
    const width = parseFloat(slide.style.width);
    const height = parseFloat(slide.style.height);
    if (!(width > 0 && height > 0)) throw new Error("The slide has no size");
    const markup = new XMLSerializer().serializeToString(slide);
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"><foreignObject width="100%" height="100%">${markup}</foreignObject></svg>`;
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }
  throw new Error(`A ${data.kind} file has no document thumbnail`);
}
