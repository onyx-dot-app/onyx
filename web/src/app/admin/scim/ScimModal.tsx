import { SvgDownload, SvgKey, SvgRefreshCw } from "@opal/icons";
import { Interactive, Hoverable } from "@opal/core";
import { Section } from "@/layouts/general-layouts";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { toast } from "@/hooks/useToast";
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
// Helpers
// ---------------------------------------------------------------------------

async function copyToClipboard(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Token copied to clipboard");
  } catch {
    toast.error("Failed to copy token");
  }
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
  switch (view.kind) {
    case "regenerate":
      return (
        <ConfirmationModalLayout
          icon={SvgRefreshCw}
          title="Regenerate SCIM Token"
          onClose={onClose}
          submit={
            <Button
              disabled={isSubmitting}
              variant="danger"
              onClick={onRegenerate}
            >
              Regenerate Token
            </Button>
          }
        >
          <Section alignItems="start" gap={0.5}>
            <Text as="p" text03>
              Your current SCIM token will be revoked and a new token will be
              generated. You will need to update the token on your identity
              provider before SCIM provisioning will resume.
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
              title="SCIM Token"
              description="Save this key before continuing. It won't be shown again."
              onClose={onClose}
            />
            <Modal.Body>
              <Hoverable.Root group="token">
                <Interactive.Stateless
                  onClick={() => copyToClipboard(view.rawToken)}
                >
                  <InputTextArea
                    value={view.rawToken}
                    readOnly
                    autoResize
                    resizable={false}
                    rows={2}
                    className="font-main-ui-mono break-all cursor-pointer [&_textarea]:cursor-pointer"
                    rightSection={
                      <div onClick={(e) => e.stopPropagation()}>
                        <Hoverable.Item group="token" variant="appear-on-hover">
                          <CopyIconButton getCopyText={() => view.rawToken} />
                        </Hoverable.Item>
                      </div>
                    }
                  />
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
                    Download
                  </Button>
                }
                submit={
                  <Button
                    autoFocus
                    onClick={() => copyToClipboard(view.rawToken)}
                  >
                    Copy Token
                  </Button>
                }
              />
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      );
  }
}
