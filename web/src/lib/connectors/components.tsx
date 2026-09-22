"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgPlusCircle } from "@opal/icons";
import type { SourceMetadata } from "@/lib/search/types";

export interface ConnectorSourceCardProps {
  sourceMetadata: SourceMetadata;
  /** Translated one-line summary of what the source indexes, shown under its name. */
  description: string;
  /** Where the card and its add button lead: the setup wizard, or an
   * existing federated connector's edit page. */
  navigationUrl: Route;
}

/**
 * One source in the connector catalog: the card counterpart to the
 * "Add Provider" cards on the Language Models page. The whole card is the
 * target; the add button repeats it for discoverability.
 */
export function ConnectorSourceCard({
  sourceMetadata,
  description,
  navigationUrl,
}: ConnectorSourceCardProps) {
  const t = useTranslations("admin.addConnector");
  const router = useRouter();
  const navigate = () => router.push(navigationUrl);

  return (
    <SelectCard
      state="empty"
      padding={2}
      rounding={4}
      // Lets the catalog find the first card to focus from the search field.
      data-source-card=""
      // The add button inside is labelled "Connect <name>", so an exact
      // match on the bare name reaches the card alone.
      aria-label={sourceMetadata.displayName}
      onClick={navigate}
    >
      <ContentAction
        icon={sourceMetadata.icon}
        title={sourceMetadata.displayName}
        description={description}
        sizePreset="main-ui"
        variant="section"
        padding={2}
        rightChildren={
          <Button
            icon={SvgPlusCircle}
            prominence="tertiary"
            // The card is the tab stop; the button repeats its action for
            // pointer users only.
            tabIndex={-1}
            aria-label={t("sourceCard.connectButton.ariaLabel", {
              source: sourceMetadata.displayName,
            })}
            onClick={(e) => {
              e.stopPropagation();
              navigate();
            }}
          />
        }
      />
    </SelectCard>
  );
}
