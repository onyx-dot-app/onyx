import { useTranslations } from "next-intl";
import { IllustrationContent } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import SvgUnPlugged from "@opal/illustrations/un-plugged";
import { markdown } from "@opal/utils";
import { DOCS_BASE_URL } from "@/lib/constants";

const DEPLOYMENT_DOCS_URL = `${DOCS_BASE_URL}/deployment/getting_started/quickstart`;

/**
 * Replaces connector/indexing admin pages in Lite mode (no vector DB), where
 * indexing can't run — points users at a Standard-mode deployment instead.
 */
export default function LiteModeIndexingNotice() {
  const t = useTranslations("admin.shared");

  return (
    <Section padding={8}>
      <IllustrationContent
        illustration={SvgUnPlugged}
        title={t("liteModeNotice.title")}
        description={markdown(
          t("liteModeNotice.description", { docsUrl: DEPLOYMENT_DOCS_URL })
        )}
      />
    </Section>
  );
}
