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
import { Form, Formik, FormikState, useFormikContext } from "formik";
import { useState } from "react";
import { FiSettings } from "react-icons/fi";
import * as Yup from "yup";
import {
  EntityType,
  KGConfig,
  EntityTypeValues,
  sanitizeKGConfig,
  KGConfigRaw,
} from "./interfaces";
import { ColumnDef } from "@tanstack/react-table";
import { DataTable } from "@/components/ui/dataTable";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import Title from "@/components/ui/title";
import { redirect } from "next/navigation";

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
  "Domain names of your vendor.",
  "Domain",
  1
);

const IgnoreDomains = createDomainField(
  "ignore_domains",
  "Ignore Domains",
  "Domain names to ignore.",
  "Domain"
);

function KGConfiguration({
  kgConfig,
  onSubmitSuccess,
  setPopup,
}: {
  kgConfig: KGConfig;
  onSubmitSuccess?: () => void;
  setPopup?: (spec: PopupSpec | null) => void;
}) {
  const initialValues: KGConfig = {
    enabled: kgConfig.enabled,
    vendor: kgConfig.vendor ?? "",
    // vendor_domains: kgConfig.vendor_domains ?? [""],
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
    const body = values.enabled ? values : { enabled: false };

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
      message: "Succesfully configured Knowledge Graph.",
      type: "success",
    });
    resetForm({ values });
    onSubmitSuccess?.();
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
                subtext="The company which is providing this feature."
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

function KGEntityType({
  setPopup,
}: {
  setPopup?: (spec: PopupSpec | null) => void;
}) {
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
            className="resize-none"
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

  const {
    data: rawData,
    isLoading,
    mutate,
  } = useSWR<EntityType[]>("/api/admin/kg/entity-types", errorHandlingFetcher);

  if (isLoading || !rawData) return <></>;

  const data: EntityTypeValues = {};
  for (const entityType of rawData) {
    data[entityType.name.toLowerCase()] = entityType;
  }

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

    for (const key in data) {
      const initialValue = data[key]!;
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
    mutate();
    resetForm({ values });
  };

  const sortedData = Object.values(data);
  sortedData.sort((a, b) => {
    if (a.name < b.name) return -1;
    else if (a.name > b.name) return 1;
    return 0;
  });

  return (
    <CardSection className="flex w-min px-10">
      <Formik
        initialValues={data}
        validationSchema={validationSchema}
        onSubmit={onSubmit}
      >
        {(props) => (
          <Form>
            <DataTable columns={columns} data={sortedData} />
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
          </Form>
        )}
      </Formik>
    </CardSection>
  );
}

function ResetActionButtons({
  setPopup,
}: {
  setPopup?: (spec: PopupSpec | null) => void;
}) {
  const reset = async () => {
    const result = await fetch("/api/admin/kg/reset", { method: "PUT" });

    if (!result.ok) {
      setPopup?.({
        message: "Failed to reset Knowledge Graph.",
        type: "error",
      });
      return;
    }

    setPopup?.({
      message: "Successfully reset Knowledge Graph.",
      type: "success",
    });
  };

  return (
    <div className="border border-red-700 p-8 rounded-md flex flex-col">
      <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
        Danger
      </p>
      <div className="flex flex-col gap-y-4">
        <p>
          Resetting the Knowledge Graph will restore all of the defaults back to
          their original values. It will also perform unfathomable voodoo magic,
          turning water to wine and flesh to gold.
        </p>
        <Button variant="destructive" className="w-min" onClick={reset}>
          Reset Knowledge Graph
        </Button>
      </div>
    </div>
  );
}

function Main() {
  const [configureModalShown, setConfigureModalShown] = useState(false);
  const { data, isLoading, mutate } = useSWR<KGConfigRaw>(
    "/api/admin/kg/config",
    errorHandlingFetcher
  );
  const { popup, setPopup } = usePopup();

  if (isLoading || !data) {
    return <></>;
  }

  const kgConfig = sanitizeKGConfig(data);

  return (
    <div className="flex flex-col py-4 gap-y-8">
      {popup}
      <CardSection className="max-w-2xl text-text shadow-lg rounded-lg">
        <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
          Knowledge Graph Configuration (Private Beta)
        </p>
        <div className="flex flex-col gap-y-6">
          <p className="text-text-600">
            The Knowledge Graph feature lets you explore your data in new ways.
            Instead of searching through unstructured text, your data is
            organized as entities and their relationships, enabling powerful
            queries like:
            <div className="p-4">
              <p>- "Summarize my last 3 calls with account XYZ"</p>
              <p>
                - "How many open Jiras are assigned to John Smith, ranked by
                priority"
              </p>
            </div>
            (To use Knowledge Graph queries, you'll need a dedicated Assistant
            configured in a specific way. Please contact the Onyx team for setup
            instructions.)
          </p>
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
          <KGEntityType setPopup={setPopup} />
          <ResetActionButtons />
        </>
      )}
      {configureModalShown && (
        <Modal
          title="Configure Knowledge Graph"
          onOutsideClick={() => setConfigureModalShown(false)}
        >
          <KGConfiguration
            kgConfig={kgConfig}
            onSubmitSuccess={mutate}
            setPopup={setPopup}
          />
        </Modal>
      )}
    </div>
  );
}

export default function Page() {
  const { data: kgExposed, isLoading } = useSWR<boolean>(
    "/api/admin/kg/exposed",
    errorHandlingFetcher
  );

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
