import { useProviderStatus } from "./ProviderContext";
import Text from "@/refresh-components/texts/Text";

export function UnconfiguredLlmProviderText({
  showConfigureAPIKey,
}: {
  showConfigureAPIKey: () => void;
}) {
  const { shouldShowConfigurationNeeded } = useProviderStatus();

  return (
    <>
      {shouldShowConfigurationNeeded && (
        <Text as="p" mainUiBody text05 className="text-center w-full pb-2">
          Please note that you have not yet configured an LLM provider. You can
          configure one{" "}
          <button
            onClick={showConfigureAPIKey}
            className="text-action-link-05 hover:underline cursor-pointer"
          >
            here
          </button>
          .
        </Text>
      )}
    </>
  );
}
