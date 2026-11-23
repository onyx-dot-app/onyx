import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgDownload } from "@opal/icons";

interface DownloadButtonProps {
  fileUrl: string;
  fileName: string;
}

/** A link that downloads a file under its name, as an icon button. */
export function DownloadButton({ fileUrl, fileName }: DownloadButtonProps) {
  const t = useTranslations("chat.filePreview");

  return (
    <Button
      href={fileUrl}
      download={fileName}
      aria-label={t("downloadButton.tooltip")}
      prominence="tertiary"
      size="sm"
      icon={SvgDownload}
      tooltip={t("downloadButton.tooltip")}
    />
  );
}
