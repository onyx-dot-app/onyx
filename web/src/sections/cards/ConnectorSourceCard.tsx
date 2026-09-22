"use client";

import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgPlusCircle } from "@opal/icons";
import type { SourceMetadata } from "@/lib/search/interfaces";

export interface ConnectorSourceCardProps {
  sourceMetadata: SourceMetadata;
  /** Translated category the source belongs to, shown under its name. */
  description: string;
  /** Where the card and its add button lead: the setup wizard, or an
   * existing federated connector's edit page. */
  navigationUrl: Route;
  /** Highlights the card as the one Enter would open. */
  preSelect?: boolean;
}

/**
 * One source in the connector catalog: the card counterpart to the
 * "Add Provider" cards on the Language Models page. The whole card is the
 * target; the add button repeats it for discoverability.
 */
export default function ConnectorSourceCard({
  sourceMetadata,
  description,
  navigationUrl,
  preSelect = false,
}: ConnectorSourceCardProps) {
  const t = useTranslations("admin.addConnector");
  const router = useRouter();
  const navigate = () => router.push(navigationUrl);

  return (
    <SelectCard
      state="empty"
      padding={2}
      rounding={4}
      interaction={preSelect ? "hover" : undefined}
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
