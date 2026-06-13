"use client";

import { useState } from "react";
import CardSection from "@/components/admin/CardSection";
import { Button } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { ThreeDotsLoader } from "@/components/Loading";
import { SettingsLayouts } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@opal/utils";
import { SvgLock } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.DOCUMENT_PROCESSING;

function Main() {
  const {
    data: isApiKeySet,
    error,
    mutate,
    isLoading,
  } = useSWR<{
    unstructured_api_key: string | null;
  }>(SWR_KEYS.unstructuredApiKeySet, (url: string) =>
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
    <div className="pb-36">
      <div className="w-full max-w-2xl">
        <CardSection className="flex flex-col gap-2">
          <Text
            as="p"
            headingH3
            text05
            className="border-b border-border-01 pb-2"
          >
            使用 Unstructured API 处理
          </Text>

          <div className="flex flex-col gap-2">
            <Text as="p" mainContentBody text04 className="leading-relaxed">
              Unstructured 会从 .pdf、.docx、.png、.pptx 等格式中提取并转换复杂数据，
              生成可供 Glomi AI 摄取的干净文本。提供 API Key 后即可启用 Unstructured 文档处理。
            </Text>
            <Text as="p" mainContentMuted text03>
              <span className="font-main-ui-action text-text-03">注意：</span>{" "}
              这会将文档发送到 Unstructured 服务器进行处理。
            </Text>
            <Text as="p" mainContentBody text04 className="leading-relaxed">
              进一步了解 Unstructured{" "}
              <a
                href="https://docs.unstructured.io/welcome"
                target="_blank"
                rel="noopener noreferrer"
                className="text-action-link-05 underline-offset-4 hover:underline"
              >
                点击这里
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
                  placeholder="输入 API Key"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                />
              )}
            </div>
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-2">
              {isApiKeySet ? (
                <>
                  <Button variant="danger" onClick={handleDelete}>
                    删除 API Key
                  </Button>
                  <Text as="p" mainContentBody text04 className="sm:mt-0">
                    更新前请先删除当前 API Key。
                  </Text>
                </>
              ) : (
                <Button variant="action" onClick={handleSave}>
                  保存 API Key
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
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} divider />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
