import React from "react";
import {
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/refresh-components/tabs/tabs";
import { DynamicProviderFields } from "./DynamicProviderFields";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";

type ProviderTabConfig = {
  tabs: Array<{
    id: string;
    label: string;
    fields: any[];
    fieldOverrides?: Record<string, any>;
    hiddenFields?: Record<string, any>;
  }>;
};

type Props = {
  llmDescriptor: WellKnownLLMProviderDescriptor;
  tabConfig: ProviderTabConfig;
  modelOptions: Array<{ label: string; value: string }>;
  onApiKeyBlur: (apiKey: string) => void;
  showApiMessage: boolean;
  apiStatus: "idle" | "loading" | "success" | "error";
  errorMessage: string;
  onFetchModels: () => Promise<void>;
  isFetchingModels: boolean;
  canFetchModels: boolean;
  activeTab: string;
  setActiveTab: (tabId: string) => void;
};

export const LLMConnectionFieldsWithTabs: React.FC<Props> = ({
  llmDescriptor,
  tabConfig,
  modelOptions,
  onApiKeyBlur,
  showApiMessage,
  apiStatus,
  errorMessage,
  onFetchModels,
  isFetchingModels,
  canFetchModels,
  activeTab,
  setActiveTab,
}) => {
  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <TabsList className="w-full">
        {tabConfig.tabs.map((tab) => (
          <TabsTrigger key={tab.id} value={tab.id} className="flex-1">
            {tab.label}
          </TabsTrigger>
        ))}
      </TabsList>
      {tabConfig.tabs.map((tab) => (
        <TabsContent key={tab.id} value={tab.id}>
          <div className="flex flex-col gap-4">
            <DynamicProviderFields
              llmDescriptor={llmDescriptor}
              fields={tab.fields}
              modelOptions={modelOptions}
              fieldOverrides={tab.fieldOverrides}
              onApiKeyBlur={onApiKeyBlur}
              showApiMessage={showApiMessage}
              apiStatus={apiStatus}
              errorMessage={errorMessage}
              onFetchModels={onFetchModels}
              isFetchingModels={isFetchingModels}
              canFetchModels={canFetchModels}
            />
          </div>
        </TabsContent>
      ))}
    </Tabs>
  );
};
