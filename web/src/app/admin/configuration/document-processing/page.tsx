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
import { cn } from "@/lib/utils";

const fetcher = (url: string) =>
  fetch(url).then((res) => {
    if (!res.ok) {
      throw new Error(`Request failed with status ${res.status}`);
    }
    return res.json();
  });

function Main() {
  const {
    data: unstructuredApiKeySet,
    error,
    mutate,
    isLoading,
  } = useSWR<boolean>("/api/search-settings/unstructured-api-key-set", fetcher);

  const {
    data: reductoConfig,
    error: reductoError,
    mutate: mutateReducto,
    isLoading: isReductoLoading,
  } = useSWR<{
    apiKey: boolean;
    apiEnv: string | null;
  }>("/api/search-settings/get-reducto-api-conf", fetcher);

  const [apiKey, setApiKey] = useState("");
  const [reductoApiKey, setReductoApiKey] = useState("");
  const [reductoEnvInput, setReductoEnvInput] = useState<string | null>(null);

  const isUnstructuredConfigured = Boolean(unstructuredApiKeySet);
  const isReductoConfigured = reductoConfig?.apiKey ?? false;
  const reductoEnvValue =
    reductoEnvInput ?? reductoConfig?.apiEnv ?? "production";

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

  const handleReductoSave = async () => {
    try {
      const params = new URLSearchParams();
      if (reductoApiKey) {
        params.set("reducto_api_key", reductoApiKey);
      }
      if (reductoEnvValue) {
        params.set("reducto_api_env", reductoEnvValue);
      }

      await fetch(
        `/api/search-settings/upsert-reducto-api-conf${
          params.size ? `?${params.toString()}` : ""
        }`,
        {
          method: "PUT",
        }
      );
      setReductoApiKey("");
      setReductoEnvInput(null);
    } catch (fetchError) {
      console.error("Failed to save Reducto config:", fetchError);
    }
    mutateReducto();
  };

  const handleReductoDelete = async () => {
    try {
      await fetch("/api/search-settings/delete-reducto-api-conf", {
        method: "DELETE",
      });
      setReductoApiKey("");
      setReductoEnvInput(null);
    } catch (fetchError) {
      console.error("Failed to delete Reducto config:", fetchError);
    }
    mutateReducto();
  };

  if (error || reductoError) {
    console.error(
      "Failed to load document processing configuration.",
      error,
      reductoError
    );
    return (
      <div className="pb-spacing-section">
        <div className="w-full max-w-2xl">
          <CardSection>
            <Text mainContentBody text04>
              Unable to load document processing configuration. Please try again
              later.
            </Text>
          </CardSection>
        </div>
      </div>
    );
  }

  if (isLoading || isReductoLoading) {
    return <ThreeDotsLoader />;
  }
  return (
    <div className="pb-36">
      <div className="w-full max-w-2xl">
        <CardSection className="flex flex-col gap-2">
          <Text headingH3 text05 className="border-b border-border-01 pb-2">
            Process with Reducto
          </Text>

          <div className="flex flex-col gap-spacing-interline">
            <Text mainContentBody text04 className="leading-relaxed">
              Reducto extracts and transforms complex data from formats like
              .pdf, .docx, .png, .pptx, images, etc. into clean text for Onyx to
              ingest. Provide an API key to enable Reducto document processing.
            </Text>
            <Text mainContentMuted text03>
              <span className="font-main-ui-action text-text-03">Note:</span>{" "}
              this will send documents to Reducto servers for processing.
            </Text>
            <Text mainContentBody text04 className="leading-relaxed">
              Learn more about Reducto{" "}
              <a
                href="https://docs.reducto.ai/overview"
                target="_blank"
                rel="noopener noreferrer"
                className="text-action-link-05 underline-offset-4 hover:underline"
              >
                here
              </a>
              .
            </Text>
            <div className="pt-1.5">
              {isReductoConfigured ? (
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
                  placeholder="Enter Reducto API Key"
                  value={reductoApiKey}
                  onChange={(e) => setReductoApiKey(e.target.value)}
                />
              )}
            </div>
            <div className="flex flex-col gap-spacing-interline">
              <Text mainContentBody text04>
                Environment
              </Text>
              <Text mainContentMuted text03>
                <span className="font-main-ui-action text-text-03">Note:</span>{" "}
                defaults to <code>production</code>. Supported values:{" "}
                <code>production</code>, <code>eu</code>, <code>au</code>.
              </Text>
              <InputTypeIn
                placeholder="production"
                value={reductoEnvValue}
                onChange={(e) => setReductoEnvInput(e.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2 desktop:flex-row desktop:items-center desktop:gap-2">
              {isReductoConfigured ? (
                <>
                  <Button onClick={handleReductoDelete} danger>
                    Delete Reducto Config
                  </Button>
                  <Button
                    onClick={handleReductoSave}
                    secondary
                    disabled={!reductoEnvValue}
                  >
                    Save Environment
                  </Button>
                  <Text mainContentBody text04 className="desktop:mt-0">
                    Delete the current API key before updating it. Environment
                    changes are saved immediately.
                  </Text>
                </>
              ) : (
                <Button
                  onClick={handleReductoSave}
                  action
                  disabled={!reductoApiKey || !reductoEnvValue}
                >
                  Save Reducto Config
                </Button>
              )}
            </div>
          </div>
        </CardSection>
        <CardSection className="flex flex-col gap-2 mt-4">
          <Text headingH3 text05 className="border-b border-border-01 pb-2">
            Process with Unstructured API
          </Text>

          <div className="flex flex-col gap-2">
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
            <div className="pt-1.5">
              {isUnstructuredConfigured ? (
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
              {isUnstructuredConfigured ? (
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
