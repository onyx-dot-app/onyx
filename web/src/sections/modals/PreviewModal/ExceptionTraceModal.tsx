import { useTranslations } from "next-intl";
import { Modal } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import { CopyButton } from "@opal/components";
import FloatingFooter from "@/sections/modals/PreviewModal/FloatingFooter";

interface ExceptionTraceModalProps {
  onOutsideClick: () => void;
  exceptionTrace: string;
  language?: string;
  /**
   * Modal header. Defaults to "Full Exception Trace" — the original
   * caller (`IndexAttemptsTable`) renders multi-line Python tracebacks.
   * Pass a more specific label (e.g. "Sync Error") for shorter, less
   * trace-shaped error messages.
   */
  title?: string;
}

export default function ExceptionTraceModal({
  onOutsideClick,
  exceptionTrace,
  language = "python",
  title,
}: ExceptionTraceModalProps) {
  const t = useTranslations("chat.modals.preview");

  return (
    <Modal open onOpenChange={onOutsideClick}>
      <Modal.Content width="full" height="full">
        <Modal.Header
          icon={SvgAlertTriangle}
          title={title ?? t("exceptionTrace.defaultTitle")}
          onClose={onOutsideClick}
          height="fit"
        />

        <div className="flex flex-col flex-1 min-h-0 overflow-hidden w-full bg-background-tint-01">
          <CodePreview content={exceptionTrace} language={language} normalize />
        </div>

        <FloatingFooter
          right={
            <CopyButton
              size="sm"
              tooltip={t("copyButton.tooltip")}
              getCopyText={() => exceptionTrace}
            />
          }
          codeBackground
        />
      </Modal.Content>
    </Modal>
  );
}
