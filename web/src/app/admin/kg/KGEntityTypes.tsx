import { SourceIcon } from "@/components/SourceIcon";
import React, { useState } from "react";
import { Form, Formik, FormikProps, FormikState } from "formik";
import * as Yup from "yup";
import { Button } from "@/components/ui/button";
import { TextAreaField, TextFormField } from "@/components/Field";
import { SwitchField } from "@/components/ui/switch";
import Link from "next/link";
import { EntityType } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import CollapsibleCard from "@/components/CollapsibleCard";
import { CogIcon } from "lucide-react";
import { FiSettings } from "react-icons/fi";
import { ValidSources } from "@/lib/types";
import { FaCircleQuestion } from "react-icons/fa6";

interface KGEntityTypesProps {
  kgEntityTypes: Record<string, EntityType[]>;
  setPopup?: (spec: PopupSpec | null) => void;
  refreshKGEntityTypes?: () => void;
}

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
    <div className="grid grid-cols-12 gap-4 px-8 pb-4 border-b border-neutral-600 font-semibold text-sm">
      <div className="col-span-1">Name</div>
      <div className="col-span-9">Description</div>
      <div className="col-span-1 flex justify-end">Active</div>
      <div className="col-span-1" />
    </div>
  );
}

// Custom Row Component
function TableRow({
  entityType,
  index,
}: {
  entityType: EntityType;
  index: number;
}) {
  const [dimState, setDimState] = useState(entityType.active);

  return (
    <div
      className={`grid grid-cols-12 px-8 py-4 hover:bg-accent-background-hovered transition-colors transition-opacity ${dimState ? "" : "opacity-50"}`}
    >
      <div className="col-span-1 flex items-center">
        <span className="font-medium text-sm">
          {snakeToHumanReadable(entityType.name)}
        </span>
      </div>
      <div className="col-span-9">
        <TextFormField
          name={`${entityType.grounded_source_name}[${index}].description`}
          className="w-full px-3 py-2 border rounded-md bg-background text-text focus:ring-2 focus:ring-blue-500 transition duration-200"
          label="description"
          removeLabel
        />
      </div>
      <div className="col-span-1 flex items-center justify-end">
        <SwitchField
          name={`${entityType.grounded_source_name}[${index}].active`}
          onCheckedChange={setDimState}
        />
      </div>
      <div className="col-span-1 flex items-center justify-end">
        <FiSettings size={20} color="rgb(150, 150, 150)" />
      </div>
    </div>
  );
}

export default function KGEntityTypes({
  kgEntityTypes,
  setPopup,
  refreshKGEntityTypes,
}: KGEntityTypesProps) {
  console.log(kgEntityTypes);

  // Store grouped entity types for reset
  const [groupedKGEntityTypes, setGroupedKGEntityTypes] =
    useState(kgEntityTypes);

  const validationSchema = Yup.array(
    Yup.object({
      name: Yup.string().required(),
      description: Yup.string().required(),
      active: Yup.boolean().required(),
      // max_coverage_days: Yup.date().required(),
    })
  );

  const onSubmit = async (
    values: Record<string, EntityType[]>,
    {
      resetForm,
    }: {
      resetForm: (
        nextState?: Partial<FormikState<Record<string, EntityType[]>>>
      ) => void;
    }
  ) => {
    const diffs: EntityType[] = [];

    for (const key in kgEntityTypes) {
      const initialArray = kgEntityTypes[key]!;
      const currentArray = values[key]!;
      for (let i = 0; i < initialArray.length; i++) {
        const initialValue = initialArray[i];
        const currentValue = currentArray?.[i];
        if (!initialValue || !currentValue) continue;
        const equals =
          initialValue.description === currentValue.description &&
          initialValue.active === currentValue.active;
        if (!equals) {
          diffs.push(currentValue);
        }
      }
    }

    if (diffs.length === 0) return;

    const response = await fetch("/api/admin/kg/entity-types", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(diffs),
    });

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      console.warn({ errorMsg });
      setPopup?.({
        message: "Failed to configure Entity Types.",
        type: "error",
      });
      return;
    }

    setPopup?.({
      message: "Successfully updated Entity Types.",
      type: "success",
    });

    refreshKGEntityTypes?.();

    resetForm({ values });
  };

  const reset = async (props: FormikProps<Record<string, EntityType[]>>) => {
    const result = await fetch("/api/admin/kg/reset", { method: "PUT" });

    if (!result.ok) {
      setPopup?.({
        message: "Failed to reset Knowledge Graph.",
        type: "error",
      });
      return;
    }

    const rawData = (await result.json()) as EntityType[];
    // Group by name into Record<string, EntityType[]>
    if (!Array.isArray(rawData)) {
      setPopup?.({
        message: "Unexpected response format when resetting Knowledge Graph.",
        type: "error",
      });
      return;
    }
    const newEntityTypes: Record<string, EntityType[]> = {};
    rawData.forEach((et) => {
      if (!et || !et.name) return;
      if (!newEntityTypes[et.name]) newEntityTypes[et.name] = [];
      newEntityTypes[et.name]?.push(et);
    });
    setGroupedKGEntityTypes(newEntityTypes);
    props.resetForm({ values: newEntityTypes });

    setPopup?.({
      message: "Successfully reset Knowledge Graph.",
      type: "success",
    });

    refreshKGEntityTypes?.();
  };

  function renderFormik(props: FormikProps<Record<string, EntityType[]>>) {
    return (
      <Form className="flex flex-col gap-y-8 w-full">
        <div className="flex flex-col gap-y-4 w-full">
          {Object.entries(groupedKGEntityTypes).length === 0 ? (
            <div className="flex flex-col gap-y-4">
              <p>No results available.</p>
              <p>
                To configure Knowledge Graph, first connect some{" "}
                <Link href={`/admin/add-connector`} className="underline">
                  Connectors.
                </Link>
              </p>
            </div>
          ) : (
            Object.entries(groupedKGEntityTypes).map(
              ([key, entityTypesArr]) => (
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
                        <TableRow
                          key={`${entityType.name}-${index}`}
                          entityType={entityType}
                          index={index}
                        />
                      ))}
                    </div>
                  </CollapsibleCard>
                </div>
              )
            )
          )}
          <div className="flex flex-row items-center gap-x-4 mt-4">
            <Button type="submit" variant="submit" disabled={!props.dirty}>
              Save
            </Button>
            <Button
              variant="outline"
              disabled={!props.dirty}
              onClick={() => props.resetForm()}
            >
              Cancel
            </Button>
          </div>
        </div>
        <div className="border border-red-700 p-8 rounded-md flex flex-col w-full">
          <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
            Danger
          </p>
          <div className="flex flex-col gap-y-4">
            <p>
              Resetting will delete all extracted entities and relationships and
              deactivate all entity types. After reset, you can reactivate
              entity types to begin populating the Knowledge Graph again.
            </p>
            <Button
              type="button"
              variant="destructive"
              className="w-min"
              onClick={() => reset(props)}
            >
              Reset Knowledge Graph
            </Button>
          </div>
        </div>
      </Form>
    );
  }

  return (
    <Formik
      initialValues={kgEntityTypes}
      validationSchema={validationSchema}
      onSubmit={onSubmit}
      enableReinitialize
    >
      {renderFormik}
    </Formik>
  );
}
