"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";

import React from "react";
import Text from "@/components/ui/text";
import { Modal } from "../../Modal";
import Cookies from "js-cookie";
import { useRouter } from "next/navigation";
import { COMPLETED_WELCOME_FLOW_COOKIE } from "./constants";
import { useEffect, useState } from "react";
import { ApiKeyForm } from "@/components/llm/ApiKeyForm";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { checkLlmProvider } from "./lib";
import { User } from "@/lib/types";
import { useProviderStatus } from "@/components/chat/ProviderContext";

import { usePopup } from "@/components/admin/connectors/Popup";

function setWelcomeFlowComplete() {
  Cookies.set(COMPLETED_WELCOME_FLOW_COOKIE, "true", { expires: 365 });
}

export function CompletedWelcomeFlowDummyComponent() {
  setWelcomeFlowComplete();
  return null;
}

export function WelcomeModal({ user }: { user: User | null }) {
  const { t } = useTranslation();
  const router = useRouter();

  const [providerOptions, setProviderOptions] = useState<
    WellKnownLLMProviderDescriptor[]
  >([]);
  const { popup, setPopup } = usePopup();

  const { refreshProviderInfo } = useProviderStatus();
  const clientSetWelcomeFlowComplete = async () => {
    setWelcomeFlowComplete();
    refreshProviderInfo();
    router.refresh();
  };

  useEffect(() => {
    async function fetchProviderInfo() {
      const { options } = await checkLlmProvider(user);
      setProviderOptions(options);
    }

    fetchProviderInfo();
  }, [user]);

  // We should always have options
  if (providerOptions.length === 0) {
    return null;
  }

  return (
    <>
      {popup}

      <Modal
        onOutsideClick={() => {
          setWelcomeFlowComplete();
          router.refresh();
        }}
        title={t(k.WELCOME_TO_SMARTSEARCH_TITLE)}
        width="w-full max-h-[900px] overflow-y-scroll max-w-3xl"
      >
        <div>
          <Text className="mb-4">{t(k.ONYX_BRINGS_ALL_YOUR_COMPANY_S)}</Text>
          <Text className="mb-4">{t(k.TO_GET_STARTED_WE_NEED_TO_SET)}</Text>

          <div className="max-h-[900px] overflow-y-scroll">
            <ApiKeyForm
              // Don't show success message on initial setup
              hideSuccess
              setPopup={setPopup}
              onSuccess={clientSetWelcomeFlowComplete}
              providerOptions={providerOptions}
            />
          </div>
        </div>
      </Modal>
    </>
  );
}
