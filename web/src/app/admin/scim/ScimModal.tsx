import { SvgDownload, SvgKey, SvgRefreshCw } from "@opal/icons";
import { Interactive, Hoverable } from "@opal/core";
import { Section } from "@/layouts/general-layouts";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { CopyButton } from "@opal/components";
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
    toast.success("Token 已复制到剪贴板");
  } catch {
    toast.error("复制 Token 失败");
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
          title="重新生成 SCIM Token"
          onClose={onClose}
          submit={
            <Button
              disabled={isSubmitting}
              variant="danger"
              onClick={onRegenerate}
            >
              重新生成 Token
            </Button>
          }
        >
          <Section alignItems="start" gap={0.5}>
            <Text as="p" text03>
              当前 SCIM Token 将被撤销并生成新的 Token。你需要在身份提供商中更新 Token，
              SCIM 预配才会恢复。
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
              description="继续前请保存此 Key。它不会再次显示。"
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
                          <CopyButton getCopyText={() => view.rawToken} />
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
                    下载
                  </Button>
                }
                submit={
                  <Button
                    autoFocus
                    onClick={() => copyToClipboard(view.rawToken)}
                  >
                    复制 Token
                  </Button>
                }
              />
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      );
  }
}
