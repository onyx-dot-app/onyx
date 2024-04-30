import { Popup } from "../admin/connectors/Popup";
import { useState } from "react";
import { TabGroup, TabList, Tab, TabPanels, TabPanel } from "@tremor/react";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/models/llm/interfaces";
import { LLMProviderUpdateForm } from "@/app/admin/models/llm/LLMProviderUpdateForm";
import { CustomLLMProviderUpdateForm } from "@/app/admin/models/llm/CustomLLMProviderUpdateForm";

export const ApiKeyForm = ({
  onSuccess,
  providerOptions,
}: {
  onSuccess: () => void;
  providerOptions: WellKnownLLMProviderDescriptor[];
}) => {
  const [popup, setPopup] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);

  const defaultProvider = providerOptions[0]?.name;
  const providerNameToIndexMap = new Map<string, number>();
  providerOptions.forEach((provider, index) => {
    providerNameToIndexMap.set(provider.name, index);
  });
  providerNameToIndexMap.set("custom", providerOptions.length);

  const providerIndexToNameMap = new Map<number, string>();
  Array.from(providerNameToIndexMap.keys()).forEach((key) => {
    providerIndexToNameMap.set(providerNameToIndexMap.get(key)!, key);
  });

  const [providerName, setProviderName] = useState<string>(defaultProvider);

  return (
    <div>
      {popup && <Popup message={popup.message} type={popup.type} />}
      <TabGroup
        index={providerNameToIndexMap.get(providerName) || 0}
        onIndexChange={(index) =>
          setProviderName(providerIndexToNameMap.get(index) || defaultProvider)
        }
      >
        <TabList className="mt-3 mb-4">
          <>
            {providerOptions.map((provider) => (
              <Tab key={provider.name}>
                {provider.display_name || provider.name}
              </Tab>
            ))}
            <Tab key="custom">Custom</Tab>
          </>
        </TabList>
        <TabPanels>
          {providerOptions.map((provider) => {
            return (
              <TabPanel key={provider.name}>
                <LLMProviderUpdateForm
                  llmProviderDescriptor={provider}
                  onClose={() => onSuccess()}
                  shouldMarkAsDefault
                  setPopup={setPopup}
                />
              </TabPanel>
            );
          })}
          <TabPanel key="custom">
            <CustomLLMProviderUpdateForm
              onClose={() => onSuccess()}
              shouldMarkAsDefault
              setPopup={setPopup}
            />
          </TabPanel>
        </TabPanels>
      </TabGroup>
    </div>
  );
};
