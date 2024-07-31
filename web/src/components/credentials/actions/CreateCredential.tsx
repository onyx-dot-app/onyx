import React from "react";
import { Button, Card } from "@tremor/react";
import { ValidSources } from "@/lib/types";
import { FaAccusoft } from "react-icons/fa";
import { submitCredential } from "@/components/admin/connectors/CredentialForm";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Form, Formik, FormikHelpers } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { getSourceDocLink } from "@/lib/sources";
import GDriveMain from "@/app/admin/connectors/[connector]/pages/gdrive/GoogleDrivePage";
import { Connector } from "@/lib/connectors/connectors";
import {
  Credential,
  credentialTemplates,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";
import { PlusCircleIcon } from "../../icons/icons";
import { GmailMain } from "@/app/admin/connectors/[connector]/pages/gmail/GmailPage";
import { ActionType, dictionaryType, formType } from "../types";
import { createValidationSchema } from "../lib";

export default function CreateCredential({
  hideSource,
  sourceType,
  setPopup,
  close,
  onClose = () => null,
  onSwitch,
  onSwap = async () => null,
  swapConnector,
  refresh = () => null,
}: {
  // Source information
  hideSource?: boolean; // hides docs link
  sourceType: ValidSources;

  setPopup: (popupSpec: PopupSpec | null) => void;

  // Optional toggle- close section after selection?
  close?: boolean;

  // Special handlers
  onClose?: () => void;
  // Switch currently selected credential
  onSwitch?: (selectedCredential: Credential<any>) => Promise<void>;
  // Switch currently selected credential + link with connector
  onSwap?: (selectedCredential: Credential<any>, connectorId: number) => void;

  // For swapping credentials on selection
  swapConnector?: Connector<any>;

  // Mutating parent state
  refresh?: () => void;
}) {
  const handleSubmit = async (
    values: formType,
    formikHelpers: FormikHelpers<formType>,
    action: ActionType
  ) => {
    const { setSubmitting, validateForm } = formikHelpers;

    const errors = await validateForm(values);
    if (Object.keys(errors).length > 0) {
      formikHelpers.setErrors(errors);
      return;
    }

    setSubmitting(true);
    formikHelpers.setSubmitting(true);

    const { name, ...credentialValues } = values;

    try {
      const response = await submitCredential({
        credential_json: credentialValues,
        admin_public: true,
        name: name,
        source: sourceType,
      });

      const { message, isSuccess, credential } = response;

      if (!credential) {
        throw new Error("No credential returned");
      }

      if (isSuccess && swapConnector) {
        if (action === "createAndSwap") {
          onSwap(credential, swapConnector.id);
        } else {
          setPopup({ type: "success", message: "Created new credneital!!" });
          setTimeout(() => setPopup(null), 4000);
        }
        onClose();
      } else {
        setPopup({ message, type: isSuccess ? "success" : "error" });
      }

      if (close) {
        onClose();
      }
      await refresh();

      if (onSwitch) {
        onSwitch(response?.credential!);
      }
    } catch (error) {
      console.error("Error submitting credential:", error);
      setPopup({ message: "Error submitting credential", type: "error" });
    } finally {
      formikHelpers.setSubmitting(false);
    }
  };

  if (sourceType == "gmail") {
    return <GmailMain />;
  }

  if (sourceType == "google_drive") {
    return <GDriveMain />;
  }

  const credentialTemplate: dictionaryType = credentialTemplates[sourceType];
  const validationSchema = createValidationSchema(credentialTemplate);

  return (
    <Formik
      initialValues={{
        name: "",
      }}
      validationSchema={validationSchema}
      onSubmit={() => {}} // This will be overridden by our custom submit handlers
    >
      {(formikProps) => (
        <Form>
          {!hideSource && (
            <p className="text-sm">
              Check our
              <a
                className="text-blue-600 hover:underline"
                target="_blank"
                href={getSourceDocLink(sourceType) || ""}
              >
                {" "}
                docs{" "}
              </a>
              for information on setting up this connector.
            </p>
          )}
          <Card className="!border-0 mt-4">
            <TextFormField
              name="name"
              placeholder="(Optional) credential name.."
              label="Name:"
            />
            {Object.entries(credentialTemplate).map(([key, val]) => (
              <TextFormField
                key={key}
                name={key}
                placeholder={val}
                label={getDisplayNameForCredentialKey(key)}
                type={
                  key.toLowerCase().includes("token") ||
                  key.toLowerCase().includes("password")
                    ? "password"
                    : "text"
                }
              />
            ))}
            {!swapConnector && (
              <div className="flex justify-between w-full">
                <Button
                  className="bg-indigo-500 hover:bg-indigo-400"
                  onClick={() =>
                    handleSubmit(formikProps.values, formikProps, "create")
                  }
                  type="button"
                  disabled={formikProps.isSubmitting}
                >
                  <div className="flex items-center gap-x-1">
                    <PlusCircleIcon size={16} className="text-indigo-100" />
                    Create
                  </div>
                </Button>
              </div>
            )}
          </Card>
          {swapConnector && (
            <div className="flex gap-x-4 w-full mt-8 justify-end">
              <Button
                className="bg-rose-500 hover:bg-rose-400 border-rose-800"
                onClick={() =>
                  handleSubmit(formikProps.values, formikProps, "createAndSwap")
                }
                type="button"
                disabled={formikProps.isSubmitting}
              >
                <div className="flex gap-x-2 items-center w-full border-none">
                  <FaAccusoft />
                  <p>Create</p>
                </div>
              </Button>
            </div>
          )}
        </Form>
      )}
    </Formik>
  );
}
