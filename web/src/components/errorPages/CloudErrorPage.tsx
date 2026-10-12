import { useTranslations } from "next-intl";
import Text from "@/refresh-components/texts/Text";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { useSettings } from "@/lib/settings/hooks";

export default function CloudError() {
  const t = useTranslations("common.errorPages.maintenance");
  const { appName } = useSettings();
  return (
    <ErrorPageLayout>
      <Text as="p" headingH2>
        {t("heading.title")}
      </Text>

      <Text as="p" text03>
        {t("checkBack.description", { appName })}
      </Text>

      <Text as="p" text03>
        {t("apology.description")}
      </Text>
    </ErrorPageLayout>
  );
}
