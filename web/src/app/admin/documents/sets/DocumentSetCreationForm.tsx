"use client";

import { Form, Formik } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  createDocumentSet,
  updateDocumentSet,
  DocumentSetCreationRequest,
} from "./lib";
import {
  ConnectorStatus,
  DocumentSetSummary,
  UserGroup,
  UserRole,
  FederatedConnectorConfig,
} from "@/lib/types";
import { TextFormField } from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import React, { useEffect, useState } from "react";
import { useUser } from "@/components/user/UserProvider";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";
import { NonSelectableConnectors } from "@/components/NonSelectableConnectors";
import { FederatedConnectorSelector } from "@/components/FederatedConnectorSelector";
import { useFederatedConnectors } from "@/lib/hooks";

interface SetCreationPopupProps {
  ccPairs: ConnectorStatus<any, any>[];
  userGroups: UserGroup[] | undefined;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  existingDocumentSet?: DocumentSetSummary;
}

export const DocumentSetCreationForm = ({
  ccPairs,
  userGroups,
  onClose,
  setPopup,
  existingDocumentSet,
}: SetCreationPopupProps) => {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const isUpdate = existingDocumentSet !== undefined;
  const [localCcPairs, setLocalCcPairs] = useState(ccPairs);
  const { user } = useUser();
  const { data: federatedConnectors } = useFederatedConnectors();

  useEffect(() => {
    if (existingDocumentSet?.is_public) {
      return;
    }
  }, [existingDocumentSet?.is_public]);

  return (
    <div className="max-w-full mx-auto">
      <Formik<DocumentSetCreationRequest>
        initialValues={{
          name: existingDocumentSet?.name ?? "",
          description: existingDocumentSet?.description ?? "",
          cc_pair_ids:
            existingDocumentSet?.cc_pair_summaries.map(
              (ccPairSummary) => ccPairSummary.id
            ) ?? [],
          is_public: existingDocumentSet?.is_public ?? true,
          users: existingDocumentSet?.users ?? [],
          groups: existingDocumentSet?.groups ?? [],
          federated_connectors:
            existingDocumentSet?.federated_connector_summaries?.map((fc) => ({
              federated_connector_id: fc.id,
              entities: fc.entities,
            })) ?? [],
        }}
        validationSchema={Yup.object()
          .shape({
            name: Yup.string().required("Please enter a name for the set"),
            description: Yup.string().optional(),
            cc_pair_ids: Yup.array().of(Yup.number().required()),
            federated_connectors: Yup.array().of(
              Yup.object().shape({
                federated_connector_id: Yup.number().required(),
                entities: Yup.object().required(),
              })
            ),
          })
          .test(
            "at-least-one-connector",
            "Please select at least one connector (regular or federated)",
            function (values) {
              const hasRegularConnectors =
                values.cc_pair_ids && values.cc_pair_ids.length > 0;
              const hasFederatedConnectors =
                values.federated_connectors &&
                values.federated_connectors.length > 0;
              return hasRegularConnectors || hasFederatedConnectors;
            }
          )}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);
          // If the document set is public, then we don't want to send any groups
          const processedValues = {
            ...values,
            groups: values.is_public ? [] : values.groups,
          };

          let response;
          if (isUpdate) {
            response = await updateDocumentSet({
              id: existingDocumentSet.id,
              ...processedValues,
              users: processedValues.users,
            });
          } else {
            response = await createDocumentSet(processedValues);
          }
          formikHelpers.setSubmitting(false);
          if (response.ok) {
            setPopup({
              message: isUpdate
                ? "Successfully updated document set!"
                : "Successfully created document set!",
              type: "success",
            });
            onClose();
          } else {
            const errorMsg = await response.text();
            setPopup({
              message: isUpdate
                ? `Error updating document set - ${errorMsg}`
                : `Error creating document set - ${errorMsg}`,
              type: "error",
            });
          }
        }}
      >
        {(props) => {
          // Filter visible cc pairs for curator role
          const visibleCcPairs =
            user?.role === UserRole.CURATOR
              ? localCcPairs.filter(
                  (ccPair) =>
                    ccPair.access_type === "public" ||
                    (ccPair.groups.length > 0 &&
                      props.values.groups.every((group) =>
                        ccPair.groups.includes(group)
                      ))
                )
              : localCcPairs;

          // Filter non-visible cc pairs for curator role
          const nonVisibleCcPairs =
            user?.role === UserRole.CURATOR
              ? localCcPairs.filter(
                  (ccPair) =>
                    !(ccPair.access_type === "public") &&
                    (ccPair.groups.length === 0 ||
                      !props.values.groups.every((group) =>
                        ccPair.groups.includes(group)
                      ))
                )
              : [];

          // Deselect filtered out cc pairs
          if (user?.role === UserRole.CURATOR) {
            const visibleCcPairIds = visibleCcPairs.map(
              (ccPair) => ccPair.cc_pair_id
            );
            props.values.cc_pair_ids = props.values.cc_pair_ids.filter((id) =>
              visibleCcPairIds.includes(id)
            );
          }

          return (
            <Form className="space-y-6 w-full ">
              <div className="space-y-4 w-full">
                <TextFormField
                  name="name"
                  label="Name:"
                  placeholder="A name for the document set"
                  autoCompleteDisabled={true}
                />
                <TextFormField
                  name="description"
                  label="Description:"
                  placeholder="Describe what the document set represents"
                  autoCompleteDisabled={true}
                  optional={true}
                />

                {isPaidEnterpriseFeaturesEnabled && (
                  <IsPublicGroupSelector
                    formikProps={props}
                    objectName="document set"
                  />
                )}
              </div>

              <div className="my-6 border-t border-border-02" />

              <div className="space-y-6">
                {user?.role === UserRole.CURATOR ? (
                  <>
                    <ConnectorMultiSelect
                      name="cc_pair_ids"
                      label={`Connectors available to ${
                        userGroups && userGroups.length > 1
                          ? "the selected group"
                          : "the group you curate"
                      }`}
                      connectors={visibleCcPairs}
                      selectedIds={props.values.cc_pair_ids}
                      onChange={(selectedIds) => {
                        props.setFieldValue("cc_pair_ids", selectedIds);
                      }}
                      placeholder="Search for connectors..."
                    />

                    <NonSelectableConnectors
                      connectors={nonVisibleCcPairs}
                      title={`Connectors not available to the ${
                        userGroups && userGroups.length > 1
                          ? `group${
                              props.values.groups.length > 1 ? "s" : ""
                            } you have selected`
                          : "group you curate"
                      }`}
                      description="Only connectors that are directly assigned to the group you are trying to add the document set to will be available."
                    />
                  </>
                ) : (
                  <ConnectorMultiSelect
                    name="cc_pair_ids"
                    label="Pick your connectors"
                    connectors={visibleCcPairs}
                    selectedIds={props.values.cc_pair_ids}
                    onChange={(selectedIds) => {
                      props.setFieldValue("cc_pair_ids", selectedIds);
                    }}
                    placeholder="Search for connectors..."
                  />
                )}

                {/* Federated Connectors Section */}
                {federatedConnectors && federatedConnectors.length > 0 && (
                  <>
                    <div className="my-4 border-t border-border-02" />
                    <FederatedConnectorSelector
                      name="federated_connectors"
                      label="Federated Connectors"
                      federatedConnectors={federatedConnectors}
                      selectedConfigs={props.values.federated_connectors}
                      onChange={(selectedConfigs) => {
                        props.setFieldValue(
                          "federated_connectors",
                          selectedConfigs
                        );
                      }}
                      placeholder="Search for federated connectors..."
                    />
                  </>
                )}
              </div>

              <div className="flex mt-6 pt-4 border-t border-border-02">
                <Button
                  type="submit"
                  disabled={props.isSubmitting}
                  className="w-56 mx-auto"
                  primary
                >
                  {isUpdate ? "Update Document Set" : "Create Document Set"}
                </Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </div>
  );
};
