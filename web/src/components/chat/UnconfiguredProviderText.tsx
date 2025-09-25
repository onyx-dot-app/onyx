"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../i18n/keys";
import { useProviderStatus } from "./ProviderContext";

export default function CredentialNotConfigured({
  showConfigureAPIKey,
  noSources,
}: {
  showConfigureAPIKey: () => void;
  noSources?: boolean;
}) {
  const { t } = useTranslation();
  const { shouldShowConfigurationNeeded } = useProviderStatus();

  return (
    <>
      {noSources ? (
        <p className="text-base text-center w-full text-subtle">
          {t(k.YOU_HAVE_NOT_YET_ADDED_ANY_SOU)}{" "}
          <a
            href="/admin/add-connector"
            className="text-link hover:underline cursor-pointer"
          >
            {t(k.A_SOURCE)}
          </a>{" "}
          {t(k.TO_CONTINUE)}
        </p>
      ) : (
        shouldShowConfigurationNeeded && (
          <p className="text-base text-center w-full text-subtle">
            {t(k.PLEASE_NOTE_THAT_YOU_HAVE_NOT)}{" "}
            <button
              onClick={showConfigureAPIKey}
              className="text-link hover:underline cursor-pointer"
            >
              {t(k.HERE)}
            </button>
            {t(k._8)}
          </p>
        )
      )}
    </>
  );
}
