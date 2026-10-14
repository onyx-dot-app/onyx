"use client";

import { useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgArrowRight, SvgChevronRight, SvgGlobe } from "@opal/icons";
import { getFileIcon } from "@/lib/utils";
import type { OutputCard } from "@/app/craft/types/streamingTypes";

interface TurnOutputCardsProps {
  outputs: readonly OutputCard[];
  onOpen: (output: OutputCard) => void;
  onShowAll: () => void;
}

export default function TurnOutputCards({
  outputs,
  onOpen,
  onShowAll,
}: TurnOutputCardsProps) {
  const t = useTranslations("craft.turnOutputs");
  if (outputs.length === 0) return null;

  return (
    <div
      className="flex flex-col gap-2 pt-2 motion-safe:animate-in motion-safe:fade-in motion-safe:duration-150"
      data-testid={`craft-turn-outputs-${outputs[0]?.turn_index}`}
    >
      {outputs.slice(0, 3).map((output) => {
        const name = output.kind === "app" ? t("appTitle") : output.name;
        const fileType = output.name.split(".").slice(1).at(-1)?.toUpperCase();
        const folder = output.path
          .replace(/^outputs\//, "")
          .split("/")
          .slice(0, -1)
          .join("/");
        const description = output.deleted
          ? t("unavailable")
          : output.kind === "app"
            ? t("app")
            : [fileType, folder].filter(Boolean).join(" · ");

        return (
          <SelectCard
            key={output.id}
            data-testid={`craft-output-card-${output.id}`}
            role={output.deleted ? "group" : "button"}
            aria-label={name}
            aria-disabled={output.deleted || undefined}
            state="filled"
            padding={2}
            rounding={2}
            onClick={output.deleted ? undefined : () => onOpen(output)}
          >
            <ContentAction
              icon={output.kind === "app" ? SvgGlobe : getFileIcon(output.name)}
              title={name}
              description={description || undefined}
              descriptionMaxLines={1}
              sizePreset="main-ui"
              variant="section"
              padding={0}
              center
              rightChildren={
                !output.deleted && (
                  <SvgChevronRight
                    size={16}
                    className="stroke-text-03"
                    aria-hidden
                  />
                )
              }
            />
          </SelectCard>
        );
      })}
      {outputs.length > 3 && (
        <div>
          <Button
            prominence="tertiary"
            size="sm"
            rightIcon={SvgArrowRight}
            onClick={onShowAll}
          >
            {t("showAll", { count: outputs.length })}
          </Button>
        </div>
      )}
    </div>
  );
}
