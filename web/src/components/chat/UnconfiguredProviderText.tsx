import i18n from "i18next";
import k from "./../../i18n/keys";
import { useProviderStatus } from "./ProviderContext";

export default function CredentialNotConfigured({
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
          {i18n.t(k.YOU_HAVE_NOT_YET_ADDED_ANY_SOU)}{" "}
          <a
            href="/admin/add-connector"
            className="text-link hover:underline cursor-pointer"
          >
            {i18n.t(k.A_SOURCE)}
          </a>{" "}
          {i18n.t(k.TO_CONTINUE)}
        </p>
      ) : (
        shouldShowConfigurationNeeded && (
          <p className="text-base text-center w-full text-subtle">
            {i18n.t(k.PLEASE_NOTE_THAT_YOU_HAVE_NOT)}{" "}
            <button
              onClick={showConfigureAPIKey}
              className="text-link hover:underline cursor-pointer"
            >
              {i18n.t(k.HERE)}
            </button>
            {i18n.t(k._8)}
          </p>
        )
      )}
    </>
  );
}
