import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { codeVariant } from "@/sections/modals/PreviewModal/variants/codeVariant";
import { imageVariant } from "@/sections/modals/PreviewModal/variants/imageVariant";
import { pdfVariant } from "@/sections/modals/PreviewModal/variants/pdfVariant";
import { csvVariant } from "@/sections/modals/PreviewModal/variants/csvVariant";
import { markdownVariant } from "@/sections/modals/PreviewModal/variants/markdownVariant";
import { dataVariant } from "@/sections/modals/PreviewModal/variants/dataVariant";
import { unsupportedVariant } from "@/sections/modals/PreviewModal/variants/unsupportedVariant";

// Note: Order does matter for the order that filters that are hit
const PREVIEW_VARIANTS: PreviewVariant[] = [
  codeVariant,
  imageVariant,
  pdfVariant,
  csvVariant,
  dataVariant,
  markdownVariant,
];

export function resolveVariant(
  semanticIdentifier: string | null,
  mimeType: string
): PreviewVariant {
  return (
    PREVIEW_VARIANTS.find((v) => v.matches(semanticIdentifier, mimeType)) ??
    unsupportedVariant
  );
}
