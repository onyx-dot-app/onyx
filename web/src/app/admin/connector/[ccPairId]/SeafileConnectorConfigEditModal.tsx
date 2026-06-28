"use client";

import { Form, Formik } from "formik";

import { TextArrayField, TextFormField } from "@/components/Field";
import SeafileLibraryPicker from "@/components/admin/connectors/seafile/SeafileLibraryPicker";
import Modal from "@/refresh-components/Modal";
import type { Credential } from "@/lib/connectors/credentials";
import { Button } from "@opal/components";
import { SvgEdit } from "@opal/icons";

import {
  normalizeSeafileConnectorConfig,
  seafileConfigEquals,
  SeafileConnectorConfigSchema,
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
  const initialValues = normalizeSeafileConnectorConfig(config);

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="md" height="lg">
        <Modal.Header
          icon={SvgEdit}
          title="Edit Seafile Configuration"
          onClose={onClose}
        />
        <Formik<SeafileConnectorConfig>
          initialValues={initialValues}
          validationSchema={SeafileConnectorConfigSchema}
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
                    label="Base URL"
                    subtext="Your self-hosted Seafile URL, e.g. https://seafile.example.com"
                    defaultHeight="h-15"
                  />

                  <SeafileLibraryPicker
                    currentCredential={credential}
                    label="Library IDs"
                    description="Select or enter the Seafile libraries this connector should index."
                  />

                  <TextArrayField
                    name="path_prefixes"
                    label="Path Prefixes"
                    values={values}
                    subtext="Paths inside each library. Leave as / to index each configured library."
                    placeholder="Enter path prefix"
                  />

                  <TextArrayField
                    name="allowed_extensions"
                    label="Allowed Extensions"
                    values={values}
                    subtext="File extensions this connector should index."
                    placeholder="Enter extension"
                  />

                  <TextFormField
                    name="max_file_size_bytes"
                    label="Max File Size Bytes"
                    subtext="Files larger than this limit are skipped."
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
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={isSubmitting || !isValid || unchanged}
                  >
                    {isSubmitting ? "Saving..." : "Save Changes"}
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
