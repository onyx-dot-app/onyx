import { Section } from "@/layouts/general-layouts";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import { DownloadButton } from "@/sections/modals/PreviewModal/variants/shared";

export const pdfVariant: PreviewVariant = {
  matches: (_name, mime) => mime === "application/pdf",
  width: "lg",
  height: "full",
  needsTextContent: false,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <iframe
      src={`${ctx.fileUrl}#toolbar=0`}
      className="w-full h-full flex-1 min-h-0 border-none"
      title="PDF Viewer"
    />
  ),

  renderFooterLeft: () => null,
  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
