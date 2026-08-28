import { useTranslations } from "next-intl";
import { SvgDownload, SvgKey, SvgRefreshCw } from "@opal/icons";
import { Interactive, Hoverable } from "@opal/core";
import { Section } from "@/layouts/general-layouts";
import { Button, InputTextArea } from "@opal/components";
import { useFocusOnMount } from "@opal/hooks";
import Text from "@/refresh-components/texts/Text";
import { CopyButton } from "@opal/components";
import { BasicModalFooter, Modal } from "@opal/components";
import { ConfirmationModalLayout } from "@opal/layouts";
import { toast } from "@opal/layouts";
import { downloadFile } from "@/lib/download";

import type { ScimModalView } from "./interfaces";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ScimModalProps {
  view: ScimModalView;
  isSubmitting: boolean;
  onRegenerate: () => void;
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ScimModal({
  view,
  isSubmitting,
  onRegenerate,
  onClose,
}: ScimModalProps) {
  const t = useTranslations("admin.scim");
  const focusOnMount = useFocusOnMount<HTMLElement>();

  async function copyToClipboard(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(t("modal.copied.message"));
    } catch {
      toast.error(t("modal.copyFailed.error"));
    }
  }

  switch (view.kind) {
    case "regenerate":
      return (
        <ConfirmationModalLayout
          icon={SvgRefreshCw}
          title={t("modal.regenerate.title")}
          onClose={onClose}
          submit={
            <Button
              disabled={isSubmitting}
              variant="danger"
              onClick={onRegenerate}
            >
              {t("modal.regenerate.submit.label")}
            </Button>
          }
        >
          <Section alignItems="start" gap={2}>
            <Text as="p" text03>
              {t("modal.regenerate.description")}
            </Text>
          </Section>
        </ConfirmationModalLayout>
      );

    case "token":
      return (
        <Modal open onOpenChange={(open) => !open && onClose()}>
          <Modal.Content width="sm">
            <Modal.Header
              icon={SvgKey}
              title={t("modal.token.title")}
              description={t("modal.token.description")}
              onClose={onClose}
            />
            <Modal.Body>
              <Hoverable.Root group="token">
                <Interactive.Stateless
                  onClick={() => copyToClipboard(view.rawToken)}
                >
                  <div className="font-main-ui-mono break-all cursor-pointer [&_textarea]:cursor-pointer">
                    <InputTextArea
                      value={view.rawToken}
                      variant="readOnly"
                      autoResize
                      resizable={false}
                      rows={2}
                      rightSection={
                        <div
                          role="presentation"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <Hoverable.Item
                            group="token"
                            variant="appear-on-hover"
                          >
                            <CopyButton getCopyText={() => view.rawToken} />
                          </Hoverable.Item>
                        </div>
                      }
                    />
                  </div>
                </Interactive.Stateless>
              </Hoverable.Root>
            </Modal.Body>
            <Modal.Footer>
              <BasicModalFooter
                left={
                  <Button
                    prominence="secondary"
                    icon={SvgDownload}
                    onClick={() =>
                      downloadFile(`onyx-scim-token-${Date.now()}.txt`, {
                        content: view.rawToken,
                      })
                    }
                  >
                    {t("modal.token.download.label")}
                  </Button>
                }
                submit={
                  <Button
                    ref={focusOnMount}
                    onClick={() => copyToClipboard(view.rawToken)}
                  >
                    {t("modal.token.copy.label")}
                  </Button>
                }
              />
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      );
  }
}
