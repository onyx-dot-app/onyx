import { SvgDownload, SvgKey, SvgRefreshCw } from "@opal/icons";
import { Interactive } from "@opal/core";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { toast } from "@/hooks/useToast";
import { downloadFile } from "@/lib/download";

import { ScimModalView } from "./interfaces";

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
  switch (view.kind) {
    case "regenerate":
      return (
        <ConfirmationModalLayout
          icon={SvgRefreshCw}
          title="Regenerate SCIM Token"
          onClose={onClose}
          submit={
            <Button danger onClick={onRegenerate} disabled={isSubmitting}>
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
              <Interactive.Base
                group="group/token"
                onClick={async () => {
                  try {
                    await navigator.clipboard.writeText(view.rawToken);
                    toast.success("Token copied to clipboard");
                  } catch {
                    toast.error("Failed to copy token");
                  }
                }}
              >
                <InputTextArea
                  value={view.rawToken}
                  readOnly
                  autoResize
                  resizable={false}
                  rows={2}
                  className="font-main-ui-mono break-all cursor-pointer [&_textarea]:cursor-pointer"
                  rightSection={
                    <div
                      className="opacity-0 group-hover/token:opacity-100 transition-opacity"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <CopyIconButton getCopyText={() => view.rawToken} />
                    </div>
                  }
                />
              </Interactive.Base>
            </Modal.Body>
            <Modal.Footer>
              <BasicModalFooter
                left={
                  <Button
                    secondary
                    leftIcon={SvgDownload}
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
                    primary
                    onClick={async () => {
                      try {
                        await navigator.clipboard.writeText(view.rawToken);
                        toast.success("Token copied to clipboard");
                      } catch {
                        toast.error("Failed to copy token");
                      }
                    }}
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
