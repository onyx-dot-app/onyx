"use client";

import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";

export default function ActionPoliciesLoadError({
  retry,
}: {
  retry: () => void;
}) {
  const t = useTranslations("craft.actionPolicies");
  return (
    <Section height="auto" alignItems="start" gap={2}>
      <Text font="secondary-body" color="status-error-05">
        {t("loadError")}
      </Text>
      <Button onClick={retry}>{t("retry")}</Button>
    </Section>
  );
}
