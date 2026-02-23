import { Section } from "@/layouts/general-layouts";
import PreviewImage from "@/refresh-components/PreviewImage";
import { PreviewVariant } from "@/sections/modals/PreviewModal/interfaces";
import {
  DownloadButton,
  ZoomControls,
} from "@/sections/modals/PreviewModal/variants/shared";

export const imageVariant: PreviewVariant = {
  matches: (_name, mime) => mime.startsWith("image/"),
  width: "lg",
  height: "full",
  needsTextContent: false,
  headerDescription: () => "",

  renderContent: (ctx) => (
    <div
      className="flex flex-1 min-h-0 items-center justify-center p-4 transition-transform duration-300 ease-in-out"
      style={{
        transform: `scale(${ctx.zoom / 100})`,
        transformOrigin: "center",
      }}
    >
      <PreviewImage
        src={ctx.fileUrl}
        alt={ctx.fileName}
        className="max-w-full max-h-full"
      />
    </div>
  ),

  renderFooterLeft: (ctx) => (
    <ZoomControls
      zoom={ctx.zoom}
      onZoomIn={ctx.onZoomIn}
      onZoomOut={ctx.onZoomOut}
    />
  ),

  renderFooterRight: (ctx) => (
    <Section flexDirection="row" width="fit">
      <DownloadButton fileUrl={ctx.fileUrl} fileName={ctx.fileName} />
    </Section>
  ),
};
