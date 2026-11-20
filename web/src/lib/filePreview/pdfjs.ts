import { pdfjs } from "react-pdf";

// The build copies PDF.js's worker and data files here
// (tools/prepare-pdf-assets.cjs), so no script loads from another origin.
const assetRoot = `/pdfjs/${pdfjs.version}/`;
pdfjs.GlobalWorkerOptions.workerSrc = `${assetRoot}pdf.worker.min.mjs`;

/** PDF.js, with its worker and data files served from this origin. */
export { pdfjs };

/** The options for each PDF that PDF.js opens. */
export const PDF_DOCUMENT_OPTIONS = {
  cMapUrl: `${assetRoot}cmaps/`,
  cMapPacked: true,
  standardFontDataUrl: `${assetRoot}standard_fonts/`,
  wasmUrl: `${assetRoot}wasm/`,
  iccUrl: `${assetRoot}iccs/`,
  isEvalSupported: false,
};
