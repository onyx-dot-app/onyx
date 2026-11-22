import { useTranslations } from "next-intl";
import { CopyButton, Modal } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgAlertTriangle } from "@opal/icons";
import { CodeFilePreview } from "@/sections/file-preview/CodeFilePreview";
import FloatingFooter from "@/sections/file-preview/FloatingFooter";

interface ExceptionTraceModalProps {
  onOutsideClick: () => void;
  exceptionTrace: string;
  language?: string;
  /** Modal header. Defaults to "Full Exception Trace". */
  title?: string;
}

export default function ExceptionTraceModal({
  onOutsideClick,
  exceptionTrace,
  language = "python",
  title,
}: ExceptionTraceModalProps) {
  const t = useTranslations("chat.modals.preview");
  const previewT = useTranslations("chat.filePreview");

  return (
    <Modal open onOpenChange={onOutsideClick}>
      <Modal.Content width="full" height="full">
        <Modal.Header
          icon={SvgAlertTriangle}
          title={title ?? t("exceptionTrace.defaultTitle")}
          onClose={onOutsideClick}
          height="fit"
        />

        <Section
          gap={0}
          alignItems="stretch"
          className="relative min-h-0 flex-1 overflow-hidden"
        >
          <CodeFilePreview text={exceptionTrace} language={language} />
          <FloatingFooter
            right={
              <CopyButton
                size="sm"
                tooltip={previewT("copyButton.tooltip")}
                aria-label={previewT("copyButton.tooltip")}
                getCopyText={() => exceptionTrace}
              />
            }
            codeBackground
          />
        </Section>
      </Modal.Content>
    </Modal>
  );
}
