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
import { cn } from "@/lib/utils";
import { SvgLock } from "@opal/icons";

function Main() {
  const {
    data: isApiKeySet,
    error: apiKeyError,
    mutate: mutateApiKey,
    isLoading: isApiKeyLoading,
  } = useSWR<boolean>(
    "/api/search-settings/unstructured-api-key-set",
    (url: string) => fetch(url).then((res) => res.json())
  );

  const {
    data: isServerUrlSet,
    error: serverUrlError,
    mutate: mutateServerUrl,
    isLoading: isServerUrlLoading,
  } = useSWR<boolean>(
    "/api/search-settings/unstructured-server-url-set",
    (url: string) => fetch(url).then((res) => res.json())
  );

  const [apiKey, setApiKey] = useState("");
  const [serverUrl, setServerUrl] = useState("");

  const handleSaveApiKey = async () => {
    try {
      await fetch(
        `/api/search-settings/upsert-unstructured-api-key?unstructured_api_key=${encodeURIComponent(
          apiKey
        )}`,
        {
          method: "PUT",
        }
      );
    } catch (error) {
      console.error("Failed to save API key:", error);
    }
    mutateApiKey();
  };

  const handleDeleteApiKey = async () => {
    try {
      await fetch("/api/search-settings/delete-unstructured-api-key", {
        method: "DELETE",
      });
      setApiKey("");
    } catch (error) {
      console.error("Failed to delete API key:", error);
    }
    mutateApiKey();
  };

  const handleSaveServerUrl = async () => {
    try {
      await fetch(
        `/api/search-settings/upsert-unstructured-server-url?unstructured_server_url=${encodeURIComponent(
          serverUrl
        )}`,
        {
          method: "PUT",
        }
      );
    } catch (error) {
      console.error("Failed to save server URL:", error);
    }
    mutateServerUrl();
  };

  const handleDeleteServerUrl = async () => {
    try {
      await fetch("/api/search-settings/delete-unstructured-server-url", {
        method: "DELETE",
      });
      setServerUrl("");
    } catch (error) {
      console.error("Failed to delete server URL:", error);
    }
    mutateServerUrl();
  };

  if (isApiKeyLoading || isServerUrlLoading) {
    return <ThreeDotsLoader />;
  }

  return (
    <div className="pb-36">
      <div className="w-full max-w-2xl flex flex-col gap-4">
        <CardSection className="flex flex-col gap-2">
          <Text
            as="p"
            headingH3
            text05
            className="border-b border-border-01 pb-2"
          >
            Unstructured API Key
          </Text>

          <div className="flex flex-col gap-2">
            <Text as="p" mainContentBody text04 className="leading-relaxed">
              Unstructured extracts and transforms complex data from formats
              like .pdf, .docx, .png, .pptx, etc. into clean text for Onyx to
              ingest. Provide an API key to enable Unstructured document
              processing.
            </Text>
            <Text as="p" mainContentBody text04 className="leading-relaxed">
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
            <div className="pt-1.5">
              {isApiKeySet ? (
                <div
                  className={cn(
                    "flex",
                    "items-center",
                    "gap-0.5",
                    "rounded-08",
                    "border",
                    "border-border-01",
                    "bg-background-neutral-01",
                    "px-2",
                    "py-1.5"
                  )}
                >
                  <Text
                    as="p"
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
            <div className="flex flex-col gap-2 desktop:flex-row desktop:items-center desktop:gap-2">
              {isApiKeySet ? (
                <>
                  <Button onClick={handleDeleteApiKey} danger>
                    Delete API Key
                  </Button>
                  <Text as="p" mainContentBody text04 className="desktop:mt-0">
                    Delete the current API key before updating.
                  </Text>
                </>
              ) : (
                <Button onClick={handleSaveApiKey} action>
                  Save API Key
                </Button>
              )}
            </div>
          </div>
        </CardSection>

        <CardSection className="flex flex-col gap-2">
          <Text
            as="p"
            headingH3
            text05
            className="border-b border-border-01 pb-2"
          >
            Self-Hosted Server URL
          </Text>

          <div className="flex flex-col gap-2">
            <Text as="p" mainContentBody text04 className="leading-relaxed">
              If you are running a self-hosted Unstructured server, provide the
              server URL here. Leave empty to use the hosted Unstructured API.
            </Text>
            <Text as="p" mainContentMuted text03>
              <span className="font-main-ui-action text-text-03">Example:</span>{" "}
              http://localhost:8000
            </Text>
            <div className="pt-1.5">
              {isServerUrlSet ? (
                <div
                  className={cn(
                    "flex",
                    "items-center",
                    "gap-0.5",
                    "rounded-08",
                    "border",
                    "border-border-01",
                    "bg-background-neutral-01",
                    "px-2",
                    "py-1.5"
                  )}
                >
                  <Text
                    as="p"
                    mainUiMuted
                    text03
                    className="flex-1 text-text-03"
                  >
                    Server URL configured
                  </Text>
                  <SvgLock className="h-4 w-4 stroke-text-03" aria-hidden />
                </div>
              ) : (
                <InputTypeIn
                  placeholder="Enter Server URL"
                  value={serverUrl}
                  onChange={(e) => setServerUrl(e.target.value)}
                />
              )}
            </div>
            <div className="flex flex-col gap-2 desktop:flex-row desktop:items-center desktop:gap-2">
              {isServerUrlSet ? (
                <>
                  <Button onClick={handleDeleteServerUrl} danger>
                    Delete Server URL
                  </Button>
                  <Text as="p" mainContentBody text04 className="desktop:mt-0">
                    Delete to use the hosted Unstructured API.
                  </Text>
                </>
              ) : (
                <Button onClick={handleSaveServerUrl} action>
                  Save Server URL
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
    <div className="container">
      <AdminPageTitle
        title="Document Processing"
        icon={<DocumentIcon2 size={32} className="my-auto" />}
      />
      <Main />
    </div>
  );
}
