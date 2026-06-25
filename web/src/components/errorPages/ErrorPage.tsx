import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import Text from "@/refresh-components/texts/Text";
import { DOCS_BASE_URL } from "@/lib/constants";
import { SvgAlertCircle } from "@opal/icons";
import { useTranslation, Trans } from "react-i18next";

export default function Error() {
  const { t } = useTranslation();

  return (
    <ErrorPageLayout>
      <div className="flex flex-row items-center gap-2">
        <Text as="p" headingH2>
          {t("error_page.title")}
        </Text>
        <SvgAlertCircle className="w-6 h-6 stroke-text-04" />
      </div>

      <Text as="p" text03>
        {t("error_page.onyx_settings_error")}
      </Text>

      <Text as="p" text03>
        <Trans
          i18nKey="error_page.admin_documentation"
          components={{
            docLink: (
              <a
                className="text-action-link-05"
                href={`${DOCS_BASE_URL}?utm_source=app&utm_medium=error_page&utm_campaign=config_error`}
                target="_blank"
                rel="noopener noreferrer"
              />
            ),
          }}
        />
      </Text>

      <Text as="p" text03>
        <Trans
          i18nKey="error_page.discord_support"
          components={{
            discordLink: (
              <a
                className="text-action-link-05"
                href="https://discord.gg/4NA5SbzrWb"
                target="_blank"
                rel="noopener noreferrer"
              />
            ),
          }}
        />
      </Text>
    </ErrorPageLayout>
  );
}
