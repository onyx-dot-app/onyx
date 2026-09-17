import { useTranslations } from "next-intl";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import Text from "@/refresh-components/texts/Text";
import { DOCS_BASE_URL } from "@/lib/constants";
import { SvgAlertCircle } from "@opal/icons";

export default function Error() {
  const t = useTranslations("common.errorPages");
  return (
    <ErrorPageLayout>
      <div className="flex flex-row items-center gap-2">
        <Text as="p" headingH2>
          {t("configError.heading.title")}
        </Text>
        <SvgAlertCircle className="w-6 h-6 stroke-text-04" />
      </div>

      <Text as="p" text03>
        {t("configError.heading.description")}
      </Text>

      <Text as="p" text03>
        {t.rich("configError.adminHint.text", {
          docsLink: (chunks) => (
            <a
              className="text-action-selection-05"
              href={`${DOCS_BASE_URL}?utm_source=app&utm_medium=error_page&utm_campaign=config_error`}
              target="_blank"
              rel="noopener noreferrer"
            >
              {chunks}
            </a>
          ),
        })}
      </Text>

      <Text as="p" text03>
        {t.rich("needHelp.text", {
          discordLink: (chunks) => (
            <a
              className="text-action-selection-05"
              href="https://discord.gg/4NA5SbzrWb"
              target="_blank"
              rel="noopener noreferrer"
            >
              {chunks}
            </a>
          ),
        })}
      </Text>
    </ErrorPageLayout>
  );
}
