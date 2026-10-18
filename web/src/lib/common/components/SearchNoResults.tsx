"use client";

import { useTranslations } from "next-intl";
import { IllustrationContent } from "@opal/layouts";
import { SvgNotFound } from "@opal/illustrations";

/**
 * The empty state for a search that matched nothing. Use it only when a
 * search query caused the empty list; a list that is empty on its own
 * needs its own empty state.
 */
export default function SearchNoResults() {
  const t = useTranslations("common.searchNoResults");
  return (
    <IllustrationContent
      illustration={SvgNotFound}
      title={t("title")}
      description={t("description")}
    />
  );
}
