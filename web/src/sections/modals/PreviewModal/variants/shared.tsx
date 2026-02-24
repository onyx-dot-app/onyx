import { Button } from "@opal/components";
import { SvgDownload, SvgZoomIn, SvgZoomOut } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import { Section } from "@/layouts/general-layouts";

interface DownloadButtonProps {
  fileUrl: string;
  fileName: string;
}

export function DownloadButton({ fileUrl, fileName }: DownloadButtonProps) {
  return (
    <a href={fileUrl} download={fileName}>
      <Button
        prominence="tertiary"
        size="sm"
        icon={SvgDownload}
        tooltip="Download"
      />
    </a>
  );
}

interface CopyButtonProps {
  getText: () => string;
}

export function CopyButton({ getText }: CopyButtonProps) {
  return (
    <CopyIconButton getCopyText={getText} tooltip="Copy content" size="sm" />
  );
}

interface ZoomControlsProps {
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
}

export function ZoomControls({ zoom, onZoomIn, onZoomOut }: ZoomControlsProps) {
  return (
    <div className="rounded-12 bg-background-tint-00 p-1 shadow-lg">
      <Section flexDirection="row" width="fit">
        <Button
          prominence="tertiary"
          size="sm"
          icon={SvgZoomOut}
          onClick={onZoomOut}
          tooltip="Zoom Out"
        />
        <Text mainUiMono text03>
          {zoom}%
        </Text>
        <Button
          prominence="tertiary"
          size="sm"
          icon={SvgZoomIn}
          onClick={onZoomIn}
          tooltip="Zoom In"
        />
      </Section>
    </div>
  );
}
