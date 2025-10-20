import { SourceIcon } from "@/components/SourceIcon";
import React, { useEffect, useState } from "react";
import { Switch } from "@/components/ui/switch";
import Link from "next/link";
import { EntityType, SourceAndEntityTypeView } from "@/app/admin/kg/interfaces";
import CollapsibleCard from "@/components/CollapsibleCard";
import { ValidSources } from "@/lib/types";
import { FaCircleQuestion } from "react-icons/fa6";
import { CheckmarkIcon } from "@/components/icons/icons";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { cn } from "@/lib/utils";

// Utility: Convert capitalized snake case to human readable case
function snakeToHumanReadable(str: string): string {
  return (
    str
      .toLowerCase()
      .replace(/_/g, " ")
      .replace(/\b\w/g, (match) => match.toUpperCase())
      // # TODO (@raunakab)
      // Special case to replace all instances of "Pr" with "PR".
      // This is a *dumb* implementation. If there exists a string that starts with "Pr" (e.g., "Prompt"),
      // then this line will stupidly convert it to "PRompt".
      // Fix this later (or if this becomes a problem lol).
      .replace("Pr", "PR")
  );
}

// Custom Header Component
function TableHeader() {
  return (
    <div className="grid grid-cols-12 gap-y-4 px-8 p-4 border-b bg-background-tint-00">
      <div className="col-span-1">
        <Text>Entity Name</Text>
      </div>
      <div className="col-span-10">
        <Text>Description</Text>
      </div>
      <div className="col-span-1 flex flex-1 justify-center">
        <Text>Active</Text>
      </div>
    </div>
  );
}

// Custom Row Component
function TableRow({ entityType }: { entityType: EntityType }) {
  const [entityTypeState, setEntityTypeState] = useState(entityType);
  const [descriptionSavingState, setDescriptionSavingState] = useState<
    "saving" | "saved" | "failed" | undefined
  >(undefined);

  const [timer, setTimer] = useState<NodeJS.Timeout | null>(null);
  const [checkmarkVisible, setCheckmarkVisible] = useState(false);
  const [hasMounted, setHasMounted] = useState(false);

  const handleToggle = async (checked: boolean) => {
    const response = await fetch("/api/admin/kg/entity-types", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify([{ ...entityType, active: checked }]),
    });

    if (!response.ok) return;

    setEntityTypeState({ ...entityTypeState, active: checked });
  };

  const handleDescriptionChange = async (description: string) => {
    try {
      const response = await fetch("/api/admin/kg/entity-types", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify([{ ...entityType, description }]),
      });
      if (response.ok) {
        setDescriptionSavingState("saved");
        setCheckmarkVisible(true);
        setTimeout(() => setCheckmarkVisible(false), 1000);
      } else {
        setDescriptionSavingState("failed");
        setCheckmarkVisible(false);
      }
    } catch {
      setDescriptionSavingState("failed");
      setCheckmarkVisible(false);
    } finally {
      setTimeout(() => setDescriptionSavingState(undefined), 1000);
    }
  };

  useEffect(() => {
    if (!hasMounted) {
      setHasMounted(true);
      return;
    }
    if (timer) clearTimeout(timer);
    setTimer(
      setTimeout(() => {
        setDescriptionSavingState("saving");
        setCheckmarkVisible(false);
        setTimer(
          setTimeout(
            () => handleDescriptionChange(entityTypeState.description),
            500
          )
        );
      }, 1000)
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityTypeState.description]);

  return (
    <div className="bg-background-tint-00">
      <div className="grid grid-cols-12 px-8 py-4">
        <div
          className={cn(
            "grid grid-cols-11 col-span-11 transition-opacity duration-150 ease-in-out",
            !entityTypeState.active && "opacity-60"
          )}
        >
          <div className="col-span-1 flex items-center">
            <Text>{snakeToHumanReadable(entityType.name)}</Text>
          </div>
          <div className="col-span-10 relative">
            <InputTypeIn
              placeholder="Value"
              disabled={!entityTypeState.active}
              className="w-full px-3 py-2 border"
              defaultValue={entityType.description}
              onChange={(e) =>
                setEntityTypeState({
                  ...entityTypeState,
                  description: e.target.value,
                })
              }
              onKeyDown={async (e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  if (timer) {
                    clearTimeout(timer);
                    setTimer(null);
                  }
                  setDescriptionSavingState("saving");
                  setCheckmarkVisible(false);
                  await handleDescriptionChange(
                    (e.target as HTMLInputElement).value
                  );
                }
              }}
            />
            <span
              className="absolute right-3 top-1/2 -translate-y-1/2 w-5 h-5"
              style={{ pointerEvents: "none" }}
            >
              <span
                className={cn(
                  "absolute inset-0 flex items-center justify-center transition-opacity duration-400 ease-in-out",
                  descriptionSavingState === "saving" && hasMounted
                    ? "opacity-100"
                    : "opacity-0"
                )}
                style={{ zIndex: 1 }}
              >
                <span className="inline-block w-4 h-4 align-middle border-2 border-theme-primary-04 border-t-transparent rounded-full animate-spin" />
              </span>
              <span
                className={cn(
                  "absolute inset-0 flex items-center justify-center transition-opacity duration-400 ease-in-out",
                  checkmarkVisible ? "opacity-100" : "opacity-0"
                )}
                style={{ zIndex: 2 }}
              >
                <CheckmarkIcon size={16} className="text-status-success-05" />
              </span>
            </span>
          </div>
        </div>
        <div className="grid col-span-1 items-center justify-center">
          <Switch
            checked={entityTypeState.active}
            onCheckedChange={handleToggle}
          />
        </div>
      </div>
    </div>
  );
}

interface KGEntityTypesProps {
  sourceAndEntityTypes: SourceAndEntityTypeView;
}

export default function KGEntityTypes({
  sourceAndEntityTypes,
}: KGEntityTypesProps) {
  // State to control open/close of all CollapsibleCards
  const [openCards, setOpenCards] = useState<{ [key: string]: boolean }>({});
  // State for search query
  const [search, setSearch] = useState("");

  // Initialize openCards state when data changes
  useEffect(() => {
    const initialState: { [key: string]: boolean } = {};
    Object.keys(sourceAndEntityTypes.entity_types).forEach((key) => {
      initialState[key] = true;
    });
    setOpenCards(initialState);
  }, [sourceAndEntityTypes]);

  // Handlers for expand/collapse all
  const handleExpandAll = () => {
    const newState: { [key: string]: boolean } = {};
    Object.keys(sourceAndEntityTypes.entity_types).forEach((key) => {
      newState[key] = true;
    });
    setOpenCards(newState);
  };
  const handleCollapseAll = () => {
    const newState: { [key: string]: boolean } = {};
    Object.keys(sourceAndEntityTypes.entity_types).forEach((key) => {
      newState[key] = false;
    });
    setOpenCards(newState);
  };

  // Determine if all cards are closed
  const allClosed = Object.values(openCards).every((v) => v === false);

  return (
    <div className="flex flex-col gap-y-4 w-full">
      <div className="flex flex-row items-center gap-x-1.5 mb-2">
        <InputTypeIn
          placeholder="Search source type..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        <Button
          className="h-9"
          onClick={allClosed ? handleExpandAll : handleCollapseAll}
        >
          {allClosed ? "Expand All" : "Collapse All"}
        </Button>
      </div>
      <div className="flex flex-col gap-y-4 w-full">
        {Object.entries(sourceAndEntityTypes.entity_types).length === 0 ? (
          <div className="flex flex-col gap-y-4">
            <Text text02>No results available.</Text>
            <Text text02>
              To configure Knowledge Graph, first connect some{" "}
              <Link
                href="/admin/add-connector"
                className="underline text-action-link-01"
              >
                Connectors.
              </Link>
            </Text>
          </div>
        ) : (
          Object.entries(sourceAndEntityTypes.entity_types)
            .filter(([key]) =>
              snakeToHumanReadable(key)
                .toLowerCase()
                .includes(search.toLowerCase())
            )
            .sort(([keyA], [keyB]) => keyA.localeCompare(keyB))
            .map(([key, entityTypesArr]) => {
              const stats = sourceAndEntityTypes.source_statistics[key] ?? {
                source_name: key,
                last_updated: undefined,
                entities_count: 0,
              };
              return (
                <div key={key}>
                  <CollapsibleCard
                    className="focus:outline-none focus-visible:outline-none outline-none"
                    header={
                      <span className="font-semibold text-lg flex flex-row gap-x-4 items-center">
                        {Object.values(ValidSources).includes(
                          key as ValidSources
                        ) ? (
                          <SourceIcon
                            sourceType={key as ValidSources}
                            iconSize={25}
                          />
                        ) : (
                          <FaCircleQuestion size={25} />
                        )}
                        {snakeToHumanReadable(key)}
                        <span className="ml-auto flex flex-row gap-x-16 items-center pr-16">
                          <span className="flex flex-col items-start">
                            <Text secondaryBody text02>
                              Entities Count
                            </Text>
                            <Text>{stats.entities_count}</Text>
                          </span>
                          <span className="flex flex-col items-start">
                            <Text secondaryBody text02>
                              Last Updated
                            </Text>
                            <Text>
                              {stats.last_updated
                                ? new Date(stats.last_updated).toLocaleString()
                                : "N/A"}
                            </Text>
                          </span>
                        </span>
                      </span>
                    }
                    // Use a key that changes with openCards[key] to force remount and update defaultOpen
                    key={`${key}-${openCards[key]}`}
                    defaultOpen={
                      openCards[key] !== undefined ? openCards[key] : true
                    }
                  >
                    <div className="w-full">
                      <TableHeader />
                      {entityTypesArr.map(
                        (entityType: EntityType, index: number) => (
                          <TableRow key={index} entityType={entityType} />
                        )
                      )}
                    </div>
                  </CollapsibleCard>
                </div>
              );
            })
        )}
      </div>
    </div>
  );
}
