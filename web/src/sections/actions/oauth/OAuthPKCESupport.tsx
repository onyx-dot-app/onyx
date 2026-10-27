"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { usePKCESupport } from "@/lib/oauth/hooks";

interface OAuthPKCESupportProps {
  authorizationUrl: string;
  tokenUrl: string;
}

export default function OAuthPKCESupport({
  authorizationUrl,
  tokenUrl,
}: OAuthPKCESupportProps) {
  const t = useTranslations(
    "actions.openApiAuthModal.connectionCheck.discovery"
  );
  const status = usePKCESupport(authorizationUrl, tokenUrl);
  return (
    <div role="status" aria-live="polite">
      <Text as="p" font="secondary-body" color="text-03">
        {t(status)}
      </Text>
    </div>
  );
}
