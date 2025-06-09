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
      initialValues={kgConfig}
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
          Knowledge Graph Configuration
        </p>
        <div className="flex flex-col gap-y-6">
          <p className="text-text-600">
            Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vestibulum
            imperdiet dolor ut nisl ultrices, a tempor massa cursus. Etiam a
            nisl et nisl venenatis scelerisque vel eu ex. Proin eu dolor vitae
            risus molestie sodales sed a risus.
          </p>
          <p className="text-text-600">
            Aliquam dignissim nisi quis venenatis venenatis. Suspendisse euismod
            purus eget ornare pharetra. Nullam aliquet enim ut lectus cursus,
            eget auctor nunc pulvinar. Maecenas at leo sit amet justo rutrum
            posuere sed at leo. Vestibulum efficitur leo vitae nunc eleifend
            egestas. Cras a congue ante, ac imperdiet libero.
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
        <div>
          <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
            Entity Types
          </p>
          <KGEntityType setPopup={setPopup} />
        </div>
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
