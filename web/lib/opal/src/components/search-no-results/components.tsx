"use client";

import { IllustrationContent } from "@opal/layouts";
import { SvgNotFound } from "@opal/illustrations";
import { useOpalStrings } from "@opal/strings";

/**
 * The empty state for a search that matched nothing. Use it only when a
 * search query caused the empty list; a list that is empty on its own
 * needs its own empty state.
 */
function SearchNoResults() {
  const strings = useOpalStrings();
  return (
    <IllustrationContent
      illustration={SvgNotFound}
      title={strings.searchNoResultsTitle}
      description={strings.searchNoResultsDescription}
    />
  );
}

export { SearchNoResults };
