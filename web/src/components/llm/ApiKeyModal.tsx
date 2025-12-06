"use client";

import { ApiKeyForm } from "./ApiKeyForm";
import Modal from "@/refresh-components/Modal";
import SvgKey from "@/icons/key";
import { useRouter } from "next/navigation";
import { useProviderStatus } from "../chat/ProviderContext";
import { PopupSpec } from "../admin/connectors/Popup";

export interface ApiKeyModalProps {
  hide?: () => void;
  setPopup: (popup: PopupSpec) => void;
}

export default function ApiKeyModal({ hide, setPopup }: ApiKeyModalProps) {
  const router = useRouter();

  const {
    shouldShowConfigurationNeeded,
    providerOptions,
    refreshProviderInfo,
  } = useProviderStatus();

  if (!shouldShowConfigurationNeeded) {
    return null;
  }

  return (
    <Modal open onOpenChange={hide}>
      <Modal.Content small>
        <Modal.Header
          icon={SvgKey}
          title="Configure a Generative AI Model"
          onClose={hide}
        />
        <Modal.Body>
          <div className="mb-5 text-sm text-neutral-700 dark:text-neutral-200">
            Please provide an API Key – you can always change this or switch
            models later.
            <br />
            {hide && (
              <>
                If you would rather look around first, you can{" "}
                <strong
                  onClick={() => hide()}
                  className="text-link cursor-pointer"
                >
                  skip this step
                </strong>
                .
              </>
            )}
          </div>

          <ApiKeyForm
            setPopup={setPopup}
            onSuccess={() => {
              router.refresh();
              refreshProviderInfo();
              hide?.();
            }}
            providerOptions={providerOptions}
          />
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
