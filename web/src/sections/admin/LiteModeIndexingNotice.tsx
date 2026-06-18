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
  return (
    <Section padding={2}>
      <IllustrationContent
        illustration={SvgUnPlugged}
        title="Indexing is unavailable in Lite mode"
        description={markdown(
          `This deployment runs Onyx Lite, which has no vector database — connectors and document indexing are disabled, and nothing is indexed. To connect data sources and index documents, deploy Onyx in **Standard mode**. See the [deployment guide](${DEPLOYMENT_DOCS_URL}) to get started.`
        )}
      />
    </Section>
  );
}
