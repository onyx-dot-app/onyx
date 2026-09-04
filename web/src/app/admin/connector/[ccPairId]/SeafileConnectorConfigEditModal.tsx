"use client";

import { Form, Formik } from "formik";

import { TextArrayField, TextFormField } from "@/components/Field";
import SeafileLibraryPicker from "@/components/admin/connectors/seafile/SeafileLibraryPicker";
import type { Credential } from "@/lib/connectors/credentials";
import { Button, Modal } from "@opal/components";
import { SvgEdit } from "@opal/icons";
import { useTranslations } from "next-intl";

import {
  normalizeSeafileConnectorConfig,
  seafileConfigEquals,
  createSeafileConnectorConfigSchema,
} from "./seafileConfig";
import type { SeafileConnectorConfig } from "./seafileConfig";

interface SeafileConnectorConfigEditModalProps {
  config: Partial<SeafileConnectorConfig>;
  credential: Credential<any>;
  onClose: () => void;
  onSubmit: (config: SeafileConnectorConfig) => Promise<void>;
}

export default function SeafileConnectorConfigEditModal({
  config,
  credential,
  onClose,
  onSubmit,
}: SeafileConnectorConfigEditModalProps) {
  const t = useTranslations("admin.connector.seafile");
  const initialValues = normalizeSeafileConnectorConfig(config);
  const validationSchema = createSeafileConnectorConfigSchema({
    baseUrlRequired: t("validation.baseUrlRequired"),
    baseUrlProtocol: t("validation.baseUrlProtocol"),
    libraryRequired: t("validation.libraryRequired"),
    extensionRequired: t("validation.extensionRequired"),
    extensionUnsupported: t("validation.extensionUnsupported"),
    maxFileSizeInteger: t("validation.maxFileSizeInteger"),
    maxFileSizePositive: t("validation.maxFileSizePositive"),
    maxFileSizeRequired: t("validation.maxFileSizeRequired"),
  });

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md" height="lg">
        <Modal.Header
          icon={SvgEdit}
          title={t("editModal.title")}
          onClose={onClose}
        />
        <Formik<SeafileConnectorConfig>
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={async (values, { setSubmitting }) => {
            try {
              await onSubmit(normalizeSeafileConnectorConfig(values));
              onClose();
            } finally {
              setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, isValid, setFieldValue, values }) => {
            const normalizedValues = normalizeSeafileConnectorConfig(values);
            const unchanged = seafileConfigEquals(
              normalizedValues,
              initialValues
            );

            return (
              <Form className="w-full">
                <Modal.Body>
                  <TextFormField
                    name="base_url"
                    label={t("fields.baseUrl.label")}
                    subtext={t("fields.baseUrl.description")}
                    defaultHeight="h-15"
                  />

                  <SeafileLibraryPicker
                    currentCredential={credential}
                    label={t("fields.libraries.label")}
                    description={t("fields.libraries.description")}
                  />

                  <TextArrayField
                    name="path_prefixes"
                    label={t("fields.pathPrefixes.label")}
                    values={values}
                    subtext={t("fields.pathPrefixes.description")}
                    placeholder={t("fields.pathPrefixes.placeholder")}
                  />

                  <TextArrayField
                    name="allowed_extensions"
                    label={t("fields.allowedExtensions.label")}
                    values={values}
                    subtext={t("fields.allowedExtensions.description")}
                    placeholder={t("fields.allowedExtensions.placeholder")}
                  />

                  <TextFormField
                    name="max_file_size_bytes"
                    label={t("fields.maxFileSize.label")}
                    subtext={t("fields.maxFileSize.description")}
                    type="number"
                    min={1}
                    onChange={(event) => {
                      void setFieldValue(
                        "max_file_size_bytes",
                        event.target.value === ""
                          ? undefined
                          : Number(event.target.value)
                      );
                    }}
                  />
                </Modal.Body>
                <Modal.Footer>
                  <Button
                    type="button"
                    prominence="secondary"
                    onClick={onClose}
                    disabled={isSubmitting}
                  >
                    {t("actions.cancel")}
                  </Button>
                  <Button
                    type="submit"
                    disabled={isSubmitting || !isValid || unchanged}
                  >
                    {isSubmitting ? t("actions.saving") : t("actions.save")}
                  </Button>
                </Modal.Footer>
              </Form>
            );
          }}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
