import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { codeVariant } from "@/sections/modals/PreviewModal/variants/codeVariant";
import { imageVariant } from "@/sections/modals/PreviewModal/variants/imageVariant";
import { pdfVariant } from "@/sections/modals/PreviewModal/variants/pdfVariant";
import { csvVariant } from "@/sections/modals/PreviewModal/variants/csvVariant";
import { markdownVariant } from "@/sections/modals/PreviewModal/variants/markdownVariant";
import { unsupportedVariant } from "@/sections/modals/PreviewModal/variants/unsupportedVariant";

const PREVIEW_VARIANTS: PreviewVariant[] = [
  codeVariant,
  imageVariant,
  pdfVariant,
  csvVariant,
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
