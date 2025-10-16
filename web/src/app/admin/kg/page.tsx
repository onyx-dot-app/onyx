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
import Button from "@/refresh-components/buttons/Button";
import { SwitchField } from "@/components/ui/switch";
import { Form, Formik, FormikState, useFormikContext } from "formik";
import { useState } from "react";
import * as Yup from "yup";
import {
  KGConfig,
  KGConfigRaw,
  SourceAndEntityTypeView,
} from "@/app/admin/kg/interfaces";
import { sanitizeKGConfig } from "@/app/admin/kg/utils";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import Title from "@/components/ui/title";
import { redirect } from "next/navigation";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import KGEntityTypes from "@/app/admin/kg/KGEntityTypes";
import Text from "@/refresh-components/texts/Text";
import SvgSettings from "@/icons/settings";
import { cn } from "@/lib/utils";

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
              className={cn(
                "flex flex-col gap-y-6",
                !props.values.enabled && "opacity-50"
              )}
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
            <Button disabled={!props.dirty}>Submit</Button>
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
      <CardSection className="max-w-2xl shadow-01 rounded-08 flex flex-col gap-spacing-interline">
        <Text headingH2>Knowledge Graph Configuration (Private Beta)</Text>
        <div className="flex flex-col gap-y-6">
          <div>
            <Text text03>
              The Knowledge Graph feature lets you explore your data in new
              ways. Instead of searching through unstructured text, your data is
              organized as entities and their relationships, enabling powerful
              queries like:
            </Text>
            <div className="p-spacing-paragraph">
              <Text text03>
                - &quot;Summarize my last 3 calls with account XYZ&quot;
              </Text>
              <Text text03>
                - &quot;How many open Jiras are assigned to John Smith, ranked
                by priority&quot;
              </Text>
            </div>
            <Text text03>
              (To use Knowledge Graph queries, you&apos;ll need a dedicated
              Assistant configured in a specific way. Please contact the Onyx
              team for setup instructions.)
            </Text>
          </div>
          <Text text03>
            <Title>Getting Started:</Title>
            Begin by configuring some high-level attributes, and then define the
            entities you want to model afterwards.
          </Text>
          <Button
            leftIcon={SvgSettings}
            onClick={() => setConfigureModalShown(true)}
          >
            Configure Knowledge Graph
          </Button>
        </div>
      </CardSection>
      {kgConfig.enabled && (
        <>
          <Text headingH2>Entity Types</Text>
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
