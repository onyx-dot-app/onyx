import { useTranslations } from "next-intl";
import Text from "@/refresh-components/texts/Text";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";

export default function CloudError() {
  const t = useTranslations("common.errorPages.maintenance");
  return (
    <ErrorPageLayout>
      <Text as="p" headingH2>
        {t("heading.title")}
      </Text>

      <Text as="p" text03>
        {t("checkBack.description")}
      </Text>

      <Text as="p" text03>
        {t("apology.description")}
      </Text>
    </ErrorPageLayout>
  );
}
