import { PopupSpec } from "../admin/connectors/Popup";
import { useState } from "react";
import { Tabs, TabsList, TabsContent, TabsTrigger } from "@/components/ui/tabs";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { LLMProviderUpdateForm } from "@/app/admin/configuration/llm/LLMProviderUpdateForm";
import { CustomLLMProviderUpdateForm } from "@/app/admin/configuration/llm/CustomLLMProviderUpdateForm";

export const ApiKeyForm = ({
  onSuccess,
  providerOptions,
  setPopup,
  hideSuccess,
}: {
  onSuccess: () => void;
  providerOptions: WellKnownLLMProviderDescriptor[];
  setPopup: (popup: PopupSpec) => void;
  hideSuccess?: boolean;
}) => {
  const defaultProvider = providerOptions[0]!.name;
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
      <Tabs
        defaultValue={String(providerNameToIndexMap.get(providerName) || 0)}
        onValueChange={(value) =>
          setProviderName(
            providerIndexToNameMap.get(Number(value)) || defaultProvider
          )
        }
      >
        <TabsList className="mt-3 mb-4">
          {providerOptions.map((provider) => (
            <TabsTrigger
              key={provider.name}
              value={String(providerNameToIndexMap.get(provider.name))}
            >
              {provider.display_name || provider.name}
            </TabsTrigger>
          ))}
          <TabsTrigger value={String(providerOptions.length)}>
            Custom
          </TabsTrigger>
        </TabsList>

        {providerOptions.map((provider) => (
          <TabsContent
            key={provider.name}
            value={String(providerNameToIndexMap.get(provider.name))}
          >
            <LLMProviderUpdateForm
              firstTimeConfiguration
              llmProviderDescriptor={provider}
              onClose={() => onSuccess()}
              shouldMarkAsDefault
              setPopup={setPopup}
              hideSuccess={hideSuccess}
            />
          </TabsContent>
        ))}

        <TabsContent value={String(providerOptions.length)}>
          <CustomLLMProviderUpdateForm
            onClose={() => onSuccess()}
            shouldMarkAsDefault
            setPopup={setPopup}
            hideSuccess={hideSuccess}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
};
