"use client";

import { useState } from "react";
import CardSection from "@/components/admin/CardSection";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { DocumentIcon2 } from "@/components/icons/icons";
import useSWR from "swr";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import Text from "@/refresh-components/texts/Text";
import SvgLock from "@/icons/lock";

function Main() {
  const {
    data: isApiKeySet,
    error,
    mutate,
    isLoading,
  } = useSWR<{
    unstructured_api_key: string | null;
  }>("/api/search-settings/unstructured-api-key-set", (url: string) =>
    fetch(url).then((res) => res.json())
  );

  const [apiKey, setApiKey] = useState("");

  const handleSave = async () => {
    try {
      await fetch(
        `/api/search-settings/upsert-unstructured-api-key?unstructured_api_key=${apiKey}`,
        {
          method: "PUT",
        }
      );
    } catch (error) {
      console.error("Failed to save API key:", error);
    }
    mutate();
  };

  const handleDelete = async () => {
    try {
      await fetch("/api/search-settings/delete-unstructured-api-key", {
        method: "DELETE",
      });
      setApiKey("");
    } catch (error) {
      console.error("Failed to delete API key:", error);
    }
    mutate();
  };

  if (isLoading) {
    return <ThreeDotsLoader />;
  }
  return (
    <div className="pb-spacing-section">
      <div className="w-full max-w-2xl">
        <CardSection className="flex flex-col gap-spacing-interline">
          <Text
            headingH3
            text05
            className="border-b border-border-01 pb-spacing-interline"
          >
            Process with Unstructured API
          </Text>

          <div className="flex flex-col gap-spacing-interline">
            <Text mainContentBody text04 className="leading-relaxed">
              Unstructured extracts and transforms complex data from formats
              like .pdf, .docx, .png, .pptx, etc. into clean text for Onyx to
              ingest. Provide an API key to enable Unstructured document
              processing.
            </Text>
            <Text mainContentMuted text03>
              <span className="font-main-ui-action text-text-03">Note:</span>{" "}
              this will send documents to Unstructured servers for processing.
            </Text>
            <Text mainContentBody text04 className="leading-relaxed">
              Learn more about Unstructured{" "}
              <a
                href="https://docs.unstructured.io/welcome"
                target="_blank"
                rel="noopener noreferrer"
                className="text-action-link-05 underline-offset-4 hover:underline"
              >
                here
              </a>
              .
            </Text>
            <div className="pt-spacing-interline-mini">
              {isApiKeySet ? (
                <div className="flex items-center gap-spacing-inline-mini rounded-08 border border-border-01 bg-background-neutral-01 px-spacing-interline py-spacing-interline-mini">
                  <Text
                    mainUiMuted
                    text03
                    className="flex-1 tracking-[0.3em] text-text-03"
                  >
                    ••••••••••••••••
                  </Text>
                  <SvgLock className="h-4 w-4 stroke-text-03" aria-hidden />
                </div>
              ) : (
                <InputTypeIn
                  placeholder="Enter API Key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              )}
            </div>
            <div className="flex flex-col gap-spacing-interline desktop:flex-row desktop:items-center desktop:gap-spacing-interline">
              {isApiKeySet ? (
                <>
                  <Button onClick={handleDelete} danger>
                    Delete API Key
                  </Button>
                  <Text mainContentBody text04 className="desktop:mt-0">
                    Delete the current API key before updating.
                  </Text>
                </>
              ) : (
                <Button onClick={handleSave} action>
                  Save API Key
                </Button>
              )}
            </div>
          </div>
        </CardSection>
      </div>
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Document Processing"
        icon={<DocumentIcon2 size={32} className="my-auto" />}
      />
      <Main />
    </div>
  );
}
