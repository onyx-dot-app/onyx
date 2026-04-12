"use client";

import CardSection from "@/components/admin/CardSection";
import {
  DatePickerField,
  FieldLabel,
  TextArrayField,
  TextFormField,
} from "@/components/Field";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import SwitchField from "@/refresh-components/form/SwitchField";
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
import { SWR_KEYS } from "@/lib/swr-keys";
import { toast } from "@/hooks/useToast";
import Title from "@/components/ui/title";
import { redirect } from "next/navigation";
import { useIsKGExposed } from "@/app/admin/kg/utils";
import KGEntityTypes from "@/app/admin/kg/KGEntityTypes";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";
import { SvgSettings } from "@opal/icons";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useTranslations } from "next-intl";

const route = ADMIN_ROUTES.KNOWLEDGE_GRAPH;

function createDomainField(
  name: string,
  label: string,
  subtext: string,
  placeholder: string,
  minFields?: number
) {
  return function DomainFields({ disabled = false }: { disabled?: boolean }) {
    const t = useTranslations("admin.kg");
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
  entityTypesMutate,
}: {
  kgConfig: KGConfig;
  onSubmitSuccess?: () => void;
  entityTypesMutate?: () => void;
}) {
  const t = useTranslations("admin.kg");
  const tc = useTranslations("common");
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
    vendor: Yup.string().required(t("vendorRequired")),
    vendor_domains: Yup.array(
      Yup.string().required(t("vendorDomainRequired"))
    )
      .min(1)
      .required(),
    ignore_domains: Yup.array(
      Yup.string().required(t("ignoreDomainRequired"))
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
      toast.error(t("failedToConfigureKG"));
      return;
    }

    toast.success(t("successfullyConfiguredKG"));
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
                label={t("enabled")}
                subtext={t("enabledDescription")}
              />
              <SwitchField
                name="enabled"
                onCheckedChange={(state) => {
                  if (!state) props.resetForm();
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
                label={t("vendor")}
                subtext={t("vendorDescription")}
                className="flex flex-row flex-1 w-full"
                placeholder={t("vendorPlaceholder")}
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
            <Button disabled={!props.dirty} type="submit">
              {tc("submit")}
            </Button>
          </div>
        </Form>
      )}
    </Formik>
  );
}

function Main() {
  const t = useTranslations("admin.kg");
  // Data:
  const {
    data: configData,
    isLoading: configIsLoading,
    mutate: configMutate,
  } = useSWR<KGConfigRaw>(SWR_KEYS.kgConfig, errorHandlingFetcher);
  const {
    data: sourceAndEntityTypesData,
    isLoading: entityTypesIsLoading,
    mutate: entityTypesMutate,
  } = useSWR<SourceAndEntityTypeView>(
    SWR_KEYS.kgEntityTypes,
    errorHandlingFetcher
  );

  // Local State:
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
      <CardSection className="max-w-2xl shadow-01 rounded-08 flex flex-col gap-2">
        <Text as="p" headingH2>
          {t("configurationPrivateBeta")}
        </Text>
        <div className="flex flex-col gap-y-6">
          <div>
            <Text as="p" text03>
              {t("kgDescription")}
            </Text>
            <div className="p-4">
              <Text as="p" text03>
                {t("queryExample1")}
              </Text>
              <Text as="p" text03>
                {t("queryExample2")}
              </Text>
            </div>
            <Text as="p" text03>
              {t("kgSetupNote")}
            </Text>
          </div>
          <Text as="p" text03>
            <Title>{t("gettingStarted")}</Title>
            {t("gettingStartedDescription")}
          </Text>
          <Button
            icon={SvgSettings}
            onClick={() => setConfigureModalShown(true)}
          >
            {t("configureKnowledgeGraph")}
          </Button>
        </div>
      </CardSection>
      {kgConfig.enabled && (
        <>
          <Text as="p" headingH2>
            {t("entityTypes")}
          </Text>
          <KGEntityTypes sourceAndEntityTypes={sourceAndEntityTypesData} />
        </>
      )}
      {configureModalShown && (
        <Modal open onOpenChange={() => setConfigureModalShown(false)}>
          <Modal.Content>
            <Modal.Header
              icon={SvgSettings}
              title={t("configureKnowledgeGraph")}
              onClose={() => setConfigureModalShown(false)}
            />
            <Modal.Body>
              <KGConfiguration
                kgConfig={kgConfig}
                onSubmitSuccess={async () => {
                  await configMutate();
                  setConfigureModalShown(false);
                }}
                entityTypesMutate={entityTypesMutate}
              />
            </Modal.Body>
          </Modal.Content>
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
    <SettingsLayouts.Root>
      <SettingsLayouts.Header icon={route.icon} title={route.title} separator />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
