"use client";

import { ApiKeyForm } from "./ApiKeyForm";
import { Modal } from "../Modal";
import { useRouter } from "next/navigation";
import { useProviderStatus } from "../chat_search/ProviderContext";

export const ApiKeyModal = ({ hide }: { hide: () => void }) => {
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
    <Modal
      title="Set an API Key!"
      className="max-w-3xl"
      onOutsideClick={() => hide()}
    >
      <div className="max-h-[75vh] overflow-y-auto flex flex-col px-4">
        <div>
          <div className="mb-5 text-sm">
            Please provide an API Key below in order to start using
            Danswer – you can always change this later.
            <br />
            If you&apos;d rather look around first, you can
            <strong onClick={() => hide()} className="text-link cursor-pointer">
              {" "}
              skip this step
            </strong>
            .
          </div>

          <ApiKeyForm
            onSuccess={() => {
              router.refresh();
              refreshProviderInfo();
              hide();
            }}
            providerOptions={providerOptions}
          />
        </div>
      </div>
    </Modal>
  );
};
