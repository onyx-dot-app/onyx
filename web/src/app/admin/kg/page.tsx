"use client";

import CardSection from "@/components/admin/CardSection";
import { AdminPageTitle } from "@/components/admin/Title";
import {
  DatePickerField,
  FieldLabel,
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
import { KGConfig, KGConfigRaw, SourceAndEntityTypeView } from "./interfaces";
import { sanitizeKGConfig } from "./utils";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import Title from "@/components/ui/title";
import { redirect } from "next/navigation";
import { useIsKGExposed } from "./utils";
import KGEntityTypes from "./KGEntityTypes";

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

function Main() {
  // Data:
  const {
    data: configData,
    isLoading: configIsLoading,
    mutate: configMutate,
  } = useSWR<KGConfigRaw>("/api/admin/kg/config", errorHandlingFetcher);
  const {
    data: sourceAndEntityTypesData,
    isLoading: entityTypesIsLoading,
    mutate: entityTypesMutate,
  } = useSWR<SourceAndEntityTypeView>(
    "/api/admin/kg/entity-types",
    errorHandlingFetcher
  );

  // Local State:
  const { popup, setPopup } = usePopup();
  const [configureModalShown, setConfigureModalShown] = useState(false);

  if (
    configIsLoading ||
    entityTypesIsLoading ||
    !configData ||
    !sourceAndEntityTypesData
  ) {
    return <></>;
  }

  const kgConfig = sanitizeKGConfig(configData);

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
          <p className="text-2xl font-bold text-text border-b border-b-border">
            Entity Types
          </p>
          <KGEntityTypes sourceAndEntityTypes={sourceAndEntityTypesData} />
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
