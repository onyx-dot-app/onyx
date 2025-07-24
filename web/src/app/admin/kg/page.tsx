"use client";

import CardSection from "@/components/admin/CardSection";
import { AdminPageTitle } from "@/components/admin/Title";
import {
  DatePickerField,
  FieldLabel,
  TextAreaField,
  TextArrayField,
  TextFormField,
} from "@/components/Field";
import { BrainIcon } from "@/components/icons/icons";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { SwitchField } from "@/components/ui/switch";
import {
  Form,
  Formik,
  FormikProps,
  FormikState,
  useFormikContext,
} from "formik";
import { useState } from "react";
import { FiSettings } from "react-icons/fi";
import * as Yup from "yup";
import {
  EntityType,
  KGConfig,
  EntityTypeValues,
  sanitizeKGConfig,
  KGConfigRaw,
  sanitizeKGEntityTypes,
} from "./interfaces";
import { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/ui/dataTable";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import Title from "@/components/ui/title";
import { redirect } from "next/navigation";
import Link from "next/link";
import { useIsKGExposed } from "./utils";

function createDomainField(
  name: string,
  label: string,
  subtext: string,
  placeholder: string,
  minFields?: number
) {
  return function DomainFields({ disabled = false }: { disabled?: boolean }) {
    const { values } = useFormikContext<any>();

    return (
      <TextArrayField
        name={name}
        label={label}
        subtext={subtext}
        placeholder={placeholder}
        minFields={minFields}
        values={values}
        disabled={disabled}
      />
    );
  };
}

const VendorDomains = createDomainField(
  "vendor_domains",
  "Vendor Domains",
  "Domain names of your company. Users with these email domains will be recognized as employees.",
  "Domain",
  1
);

const IgnoreDomains = createDomainField(
  "ignore_domains",
  "Ignore Domains",
  "Domain names to ignore. Users with these email domains will be excluded from the Knowledge Graph.",
  "Domain"
);

function KGConfiguration({
  kgConfig,
  onSubmitSuccess,
  setPopup,
  entityTypesMutate,
}: {
  kgConfig: KGConfig;
  onSubmitSuccess?: () => void;
  setPopup?: (spec: PopupSpec | null) => void;
  entityTypesMutate?: () => void;
}) {
  const initialValues: KGConfig = {
    enabled: kgConfig.enabled,
    vendor: kgConfig.vendor ?? "",
    vendor_domains:
      (kgConfig.vendor_domains?.length ?? 0) > 0
        ? kgConfig.vendor_domains
        : [""],
    ignore_domains: kgConfig.ignore_domains ?? [],
    coverage_start: kgConfig.coverage_start,
  };

  const enabledSchema = Yup.object({
    enabled: Yup.boolean().required(),
    vendor: Yup.string().required("Vendor is required."),
    vendor_domains: Yup.array(
      Yup.string().required("Vendor Domain is required.")
    )
      .min(1)
      .required(),
    ignore_domains: Yup.array(
      Yup.string().required("Ignore Domain is required")
    )
      .min(0)
      .required(),
    coverage_start: Yup.date().nullable(),
  });

  const disabledSchema = Yup.object({
    enabled: Yup.boolean().required(),
  });

  const validationSchema = Yup.lazy((values) =>
    values.enabled ? enabledSchema : disabledSchema
  );

  const onSubmit = async (
    values: KGConfig,
    {
      resetForm,
    }: {
      resetForm: (nextState?: Partial<FormikState<KGConfig>>) => void;
    }
  ) => {
    const { enabled, ...enableRequest } = values;
    const body = enabled ? enableRequest : {};

    const response = await fetch("/api/admin/kg/config", {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      console.warn({ errorMsg });
      setPopup?.({
        message: "Failed to configure Knowledge Graph.",
        type: "error",
      });
      return;
    }

    setPopup?.({
      message: "Successfully configured Knowledge Graph.",
      type: "success",
    });
    resetForm({ values });
    onSubmitSuccess?.();

    // Refresh entity types if KG was enabled
    if (enabled && entityTypesMutate) {
      entityTypesMutate();
    }
  };

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={onSubmit}
    >
      {(props) => (
        <Form>
          <div className="flex flex-col gap-y-6 w-full">
            <div className="flex flex-col gap-y-1">
              <FieldLabel
                name="enabled"
                label="Enabled"
                subtext="Enable or disable Knowledge Graph."
              />
              <SwitchField
                name="enabled"
                className="flex flex-1"
                onCheckedChange={(state) => {
                  props.resetForm();
                  props.setFieldValue("enabled", state);
                }}
              />
            </div>
            <div
              className={`flex flex-col gap-y-6 ${
                props.values.enabled ? "" : "opacity-50"
              }`}
            >
              <TextFormField
                name="vendor"
                label="Vendor"
                subtext="Your company name."
                className="flex flex-row flex-1 w-full"
                placeholder="My Company Inc."
                disabled={!props.values.enabled}
              />
              <VendorDomains disabled={!props.values.enabled} />
              <IgnoreDomains disabled={!props.values.enabled} />
              <DatePickerField
                name="coverage_start"
                label="Coverage Start"
                subtext="The start date of coverage for Knowledge Graph."
                startYear={2025} // TODO: remove this after public beta
                disabled={!props.values.enabled}
              />
            </div>
            <Button variant="submit" type="submit" disabled={!props.dirty}>
              Submit
            </Button>
          </div>
        </Form>
      )}
    </Formik>
  );
}

function KGEntityTypes({
  kgEntityTypes,
  sortedKGEntityTypes: sorted,
  setPopup,
  refreshKGEntityTypes,
}: {
  kgEntityTypes: EntityTypeValues;
  sortedKGEntityTypes: EntityType[];
  setPopup?: (spec: PopupSpec | null) => void;
  refreshKGEntityTypes?: () => void;
}) {
  const [sortedKGEntityTypes, setSortedKGEntityTypes] = useState(sorted);
  console.log({ sortedKGEntityTypes });

  const columns: ColumnDef<EntityType>[] = [
    {
      accessorKey: "name",
      header: "Name",
    },
    {
      accessorKey: "description",
      header: "Description",
      cell: ({ row }) => (
        <div className="h-20 w-[800px]">
          <TextAreaField
            name={`${row.original.name.toLowerCase()}.description`}
            className="resize-none border rounded-md bg-background text-text focus:ring-2 focus:ring-blue-500 transition duration-200"
          />
        </div>
      ),
    },
    {
      accessorKey: "active",
      header: "Active",
      cell: ({ row }) => (
        <SwitchField name={`${row.original.name.toLowerCase()}.active`} />
      ),
    },
  ];

  const validationSchema = Yup.array(
    Yup.object({
      active: Yup.boolean().required(),
    })
  );

  const onSubmit = async (
    values: EntityTypeValues,
    {
      resetForm,
    }: {
      resetForm: (nextState?: Partial<FormikState<EntityTypeValues>>) => void;
    }
  ) => {
    const diffs: EntityType[] = [];

    for (const key in kgEntityTypes) {
      const initialValue = kgEntityTypes[key]!;
      const currentValue = values[key]!;
      const equals =
        initialValue.description === currentValue.description &&
        initialValue.active === currentValue.active;
      if (!equals) {
        diffs.push(currentValue);
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

  const reset = async (props: FormikProps<EntityTypeValues>) => {
    const result = await fetch("/api/admin/kg/reset", { method: "PUT" });

    if (!result.ok) {
      setPopup?.({
        message: "Failed to reset Knowledge Graph.",
        type: "error",
      });
      return;
    }

    const rawData = (await result.json()) as EntityType[];
    const [newEntityTypes, newSortedEntityTypes] =
      sanitizeKGEntityTypes(rawData);
    props.resetForm({ values: newEntityTypes });
    setSortedKGEntityTypes(newSortedEntityTypes);

    setPopup?.({
      message: "Successfully reset Knowledge Graph.",
      type: "success",
    });

    refreshKGEntityTypes?.();
  };

  return (
    <Formik
      initialValues={kgEntityTypes}
      validationSchema={validationSchema}
      onSubmit={onSubmit}
    >
      {(props) => (
        <Form className="flex flex-col gap-y-8">
          <CardSection className="flex flex-col w-min px-10 gap-y-4">
            <DataTable
              columns={columns}
              data={sortedKGEntityTypes}
              emptyMessage={
                <div className="flex flex-col gap-y-4">
                  <p>No results available.</p>
                  <p>
                    To configure Knowledge Graph, first connect some {` `}
                    <Link href={`/admin/add-connector`} className="underline">
                      Connectors.
                    </Link>
                  </p>
                </div>
              }
            />
            <div className="flex flex-row items-center gap-x-4">
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
          </CardSection>
          <div className="border border-red-700 p-8 rounded-md flex flex-col w-full">
            <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
              Danger
            </p>
            <div className="flex flex-col gap-y-4">
              <p>
                Resetting will delete all extracted entities and relationships
                and deactivate all entity types. After reset, you can reactivate
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
      )}
    </Formik>
  );
}

function Main() {
  // Data:
  const {
    data: configData,
    isLoading: configIsLoading,
    mutate: configMutate,
  } = useSWR<KGConfigRaw>("/api/admin/kg/config", errorHandlingFetcher);
  const {
    data: entityTypesData,
    isLoading: entityTypesIsLoading,
    mutate: entityTypesMutate,
  } = useSWR<EntityType[]>("/api/admin/kg/entity-types", errorHandlingFetcher);

  // Local State:
  const { popup, setPopup } = usePopup();
  const [configureModalShown, setConfigureModalShown] = useState(false);

  if (
    configIsLoading ||
    entityTypesIsLoading ||
    !configData ||
    !entityTypesData
  ) {
    return <></>;
  }

  const kgConfig = sanitizeKGConfig(configData);
  const [kgEntityTypes, sortedKGEntityTypes] =
    sanitizeKGEntityTypes(entityTypesData);

  return (
    <div className="flex flex-col py-4 gap-y-8">
      {popup}
      <CardSection className="max-w-2xl text-text shadow-lg rounded-lg">
        <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
          Knowledge Graph Configuration (Private Beta)
        </p>
        <div className="flex flex-col gap-y-6">
          <div className="text-text-600">
            <p>
              The Knowledge Graph feature lets you explore your data in new
              ways. Instead of searching through unstructured text, your data is
              organized as entities and their relationships, enabling powerful
              queries like:
            </p>
            <div className="p-4">
              <p>- &quot;Summarize my last 3 calls with account XYZ&quot;</p>
              <p>
                - &quot;How many open Jiras are assigned to John Smith, ranked
                by priority&quot;
              </p>
            </div>
            <p>
              (To use Knowledge Graph queries, you&apos;ll need a dedicated
              Assistant configured in a specific way. Please contact the Onyx
              team for setup instructions.)
            </p>
          </div>
          <p className="text-text-600">
            <Title>Getting Started:</Title>
            Begin by configuring some high-level attributes, and then define the
            entities you want to model afterwards.
          </p>
          <Button
            size="lg"
            icon={FiSettings}
            onClick={() => setConfigureModalShown(true)}
          >
            Configure Knowledge Graph
          </Button>
        </div>
      </CardSection>
      {kgConfig.enabled && (
        <>
          <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
            Entity Types
          </p>
          <KGEntityTypes
            kgEntityTypes={kgEntityTypes}
            sortedKGEntityTypes={sortedKGEntityTypes}
            setPopup={setPopup}
            refreshKGEntityTypes={entityTypesMutate}
          />
        </>
      )}
      {configureModalShown && (
        <Modal
          title="Configure Knowledge Graph"
          onOutsideClick={() => setConfigureModalShown(false)}
          className="overflow-y-scroll"
        >
          <KGConfiguration
            kgConfig={kgConfig}
            setPopup={setPopup}
            onSubmitSuccess={async () => {
              await configMutate();
              setConfigureModalShown(false);
            }}
            entityTypesMutate={entityTypesMutate}
          />
        </Modal>
      )}
    </div>
  );
}

export default function Page() {
  const { kgExposed, isLoading } = useIsKGExposed();

  if (isLoading) {
    return <></>;
  }

  if (!kgExposed) {
    redirect("/");
  }

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Knowledge Graph"
        icon={<BrainIcon size={32} className="my-auto" />}
      />
      <Main />
    </div>
  );
}
