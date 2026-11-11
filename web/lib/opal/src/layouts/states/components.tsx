"use client";

import type { RichStr } from "@opal/types";
import { useOpalStrings } from "@opal/strings";
import { IllustrationContent } from "@opal/layouts/illustration-content/components";
import { PageCenter } from "@opal/layouts/page-center/components";
import SvgPlugBroken from "@opal/illustrations/plug-broken";

// ---------------------------------------------------------------------------
// ErrorState
// ---------------------------------------------------------------------------

interface ErrorStateProps {
  /** What failed, e.g. "Agents failed to load". */
  title: string | RichStr;
  /** Replaces the generic "Something went wrong" description. */
  description?: string | RichStr;
}

/** Content that failed to load, in place of a page body or a list. */
function ErrorState({ title, description }: ErrorStateProps) {
  const strings = useOpalStrings();
  return (
    <PageCenter>
      <IllustrationContent
        illustration={SvgPlugBroken}
        title={title}
        description={description ?? strings.errorStateDescription}
      />
    </PageCenter>
  );
}

export { ErrorState, type ErrorStateProps };
