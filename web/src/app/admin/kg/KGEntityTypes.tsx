import { SourceIcon } from "@/components/SourceIcon";
import React, { useEffect, useState } from "react";
import { Switch } from "@/components/ui/switch";
import Link from "next/link";
import { EntityType } from "./interfaces";
import CollapsibleCard from "@/components/CollapsibleCard";
import { FiSettings } from "react-icons/fi";
import { ValidSources } from "@/lib/types";
import { FaCircleQuestion } from "react-icons/fa6";
import { Modal } from "@/components/Modal";
import { Input } from "@/components/ui/input";
import { CheckmarkIcon } from "@/components/icons/icons";
import { entityTypesToEntityMap } from "./utils";
import { DatePicker } from "@/components/ui/datePicker";

// Utility: Convert capitalized snake case to human readable case
export function snakeToHumanReadable(str: string): string {
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
    <div className="grid grid-cols-12 gap-4 px-8 pb-4 border-b border-neutral-700 font-semibold text-sm bg-neutral-900 text-neutral-500">
      <div className="col-span-1">Name</div>
      <div className="col-span-7">Description</div>
      <div className="col-span-3 flex justify-center">Max Coverage Date</div>
      <div className="col-span-1 flex justify-center">Active</div>
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
    <div className="hover:bg-accent-background-hovered transition-colors duration-200 ease-in-out">
      <div
        className={`grid grid-cols-12 px-8 py-4 transition-opacity duration-150 ease-in-out ${entityTypeState.active ? "" : "opacity-60"}`}
      >
        <div className="col-span-1 flex items-center">
          <span className="font-medium text-sm">
            {snakeToHumanReadable(entityType.name)}
          </span>
        </div>
        <div className="col-span-7 relative">
          <Input
            disabled={!entityTypeState.active}
            className="w-full px-3 py-2 border focus:ring-2 transition-shadow"
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
              className={`absolute inset-0 flex items-center justify-center transition-opacity duration-400 ease-in-out ${
                descriptionSavingState === "saving" && hasMounted
                  ? "opacity-100"
                  : "opacity-0"
              }`}
              style={{ zIndex: 1 }}
            >
              <span className="inline-block w-4 h-4 align-middle border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            </span>
            <span
              className={`absolute inset-0 flex items-center justify-center transition-opacity duration-400 ease-in-out ${
                checkmarkVisible ? "opacity-100" : "opacity-0"
              }`}
              style={{ zIndex: 2 }}
            >
              <CheckmarkIcon size={16} className="text-green-400" />
            </span>
          </span>
        </div>
        <div className="col-span-3 flex items-center justify-center">
          <DatePicker
            selectedDate={entityTypeState.coverage_start ?? new Date()}
            setSelectedDate={(coverage_start) =>
              setEntityTypeState({ ...entityTypeState, coverage_start })
            }
            disabled={!entityTypeState.active}
          />
        </div>
        <div className="col-span-1 flex items-center justify-center pl-3">
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
  kgEntityTypes: EntityType[];
}

export default function KGEntityTypes({ kgEntityTypes }: KGEntityTypesProps) {
  const entityTypesMap = entityTypesToEntityMap(kgEntityTypes);

  return (
    <div className="flex flex-col gap-y-8 w-full">
      <div className="flex flex-col gap-y-4 w-full">
        {Object.entries(kgEntityTypes).length === 0 ? (
          <div className="flex flex-col gap-y-4">
            <p>No results available.</p>
            <p>
              To configure Knowledge Graph, first connect some{" "}
              <Link href="/admin/add-connector" className="underline">
                Connectors.
              </Link>
            </p>
          </div>
        ) : (
          Object.entries(entityTypesMap)
            .sort(([keyA], [keyB]) => keyA.localeCompare(keyB))
            .map(([key, entityTypesArr]) => (
              <div key={key}>
                <CollapsibleCard
                  header={
                    <span className="font-semibold text-lg flex flex-row gap-x-4">
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
                    </span>
                  }
                  defaultOpen={true}
                >
                  <div className="w-full pt-4">
                    <TableHeader />
                    {entityTypesArr.map((entityType, index) => (
                      <TableRow key={index} entityType={entityType} />
                    ))}
                  </div>
                </CollapsibleCard>
              </div>
            ))
        )}
      </div>
      <div className="border border-red-700 p-8 rounded-md flex flex-col w-full">
        <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
          Danger
        </p>
        <div className="flex flex-col gap-y-4">
          <p>
            Resetting will delete all extracted entities and relationships and
            deactivate all entity types. After reset, you can reactivate entity
            types to begin populating the Knowledge Graph again.
          </p>
          {/* Optionally keep or remove the reset button as needed */}
        </div>
      </div>
    </div>
  );
}
