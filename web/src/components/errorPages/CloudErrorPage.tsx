import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { useSettings } from "@/lib/settings/hooks";

export default function CloudError() {
  const t = useTranslations("common.errorPages.maintenance");
  const { appName } = useSettings();
  return (
    <ErrorPageLayout>
      <Text as="p" font="heading-h2" color="text-05">
        {t("heading.title")}
      </Text>

      <Text as="p" font="main-ui-body" color="text-03">
        {t("checkBack.description", { appName })}
      </Text>

      <Text as="p" font="main-ui-body" color="text-03">
        {t("apology.description")}
      </Text>
    </ErrorPageLayout>
  );
}
