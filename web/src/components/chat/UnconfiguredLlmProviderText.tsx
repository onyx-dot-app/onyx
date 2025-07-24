import { useProviderStatus } from "./ProviderContext";

export function UnconfiguredLlmProviderText({
  showConfigureAPIKey,
  noSources,
}: {
  showConfigureAPIKey: () => void;
  noSources?: boolean;
}) {
  const { shouldShowConfigurationNeeded } = useProviderStatus();

  return (
    <>
      {noSources ? (
        <p className="text-base text-center w-full text-subtle">
          You have not yet added any sources. Please add{" "}
          <a
            href="/admin/add-connector"
            className="text-link hover:underline cursor-pointer"
          >
            a source
          </a>{" "}
          to continue.
        </p>
      ) : (
        shouldShowConfigurationNeeded && (
          <p className="text-base text-center w-full text-subtle">
            Please note that you have not yet configured an LLM provider. You
            can configure one{" "}
            <button
              onClick={showConfigureAPIKey}
              className="text-link hover:underline cursor-pointer"
            >
              here
            </button>
            .
          </p>
        )
      )}
    </>
  );
}
