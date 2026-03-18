import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertTriangle } from "@opal/icons";
import { CodePreview } from "@/sections/modals/PreviewModal/variants/CodePreview";
import { CopyButton } from "@/sections/modals/PreviewModal/variants/shared";
import { Section } from "@/layouts/general-layouts";
import { cn } from "@/lib/utils";
import { useMemo } from "react";

interface ExceptionTraceModalProps {
  onOutsideClick: () => void;
  exceptionTrace: string;
  language?: string;
}

export default function ExceptionTraceModal({
  onOutsideClick,
  exceptionTrace,
  language = "python",
}: ExceptionTraceModalProps) {
  const lineCount = useMemo(
    () => exceptionTrace.split("\n").length,
    [exceptionTrace]
  );

  return (
    <Modal open onOpenChange={onOutsideClick}>
      <Modal.Content width="lg" height="full">
        <Modal.Header
          icon={SvgAlertTriangle}
          title="Full Exception Trace"
          onClose={onOutsideClick}
          height="fit"
        />

        <div className="flex flex-col flex-1 min-h-0 overflow-hidden w-full bg-background-tint-01">
          <CodePreview content={exceptionTrace} language={language} normalize />
        </div>

        {/* Floating footer */}
        <div
          className={cn(
            "absolute bottom-0 left-0 right-0",
            "flex items-center justify-between",
            "p-4 pointer-events-none w-full"
          )}
          style={{
            background:
              "linear-gradient(to top, var(--background-code-01) 40%, transparent)",
          }}
        >
          <div className="pointer-events-auto">
            <Text text03 mainUiBody className="select-none">
              {lineCount} {lineCount === 1 ? "line" : "lines"}
            </Text>
          </div>

          <div className="pointer-events-auto rounded-12 bg-background-tint-00 p-1 shadow-lg">
            <Section flexDirection="row" width="fit">
              <CopyButton getText={() => exceptionTrace} />
            </Section>
          </div>
        </div>
      </Modal.Content>
    </Modal>
  );
}
