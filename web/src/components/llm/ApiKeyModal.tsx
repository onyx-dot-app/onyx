"use client";
import i18n from "@/i18n/init";
import k from "./../../i18n/keys";

import { ApiKeyForm } from "./ApiKeyForm";
import { Modal } from "../Modal";
import { useRouter } from "next/navigation";
import { useProviderStatus } from "../chat/ProviderContext";
import { PopupSpec } from "../admin/connectors/Popup";

export const ApiKeyModal = ({
  hide,
  setPopup,
}: {
  hide?: () => void;
  setPopup: (popup: PopupSpec) => void;
}) => {
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
      title={i18n.t(k.CONFIGURE_AI_MODEL_TITLE)}
      width="max-w-3xl w-full"
      onOutsideClick={hide ? () => hide() : undefined}
    >
      <>
        <div className="mb-5 text-sm text-neutral-700 dark:text-neutral-200">
          {i18n.t(k.PLEASE_PROVIDE_AN_API_KEY_YO)}

          <br />
          {hide && (
            <>
              {i18n.t(k.IF_YOU_WOULD_RATHER_LOOK_AROUN)}{" "}
              <strong
                onClick={() => hide()}
                className="text-link cursor-pointer"
              >
                {i18n.t(k.SKIP_THIS_STEP)}
              </strong>
              {i18n.t(k._8)}
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
      </>
    </Modal>
  );
};
