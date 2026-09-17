"use client";

import { Form, Formik } from "formik";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import * as Yup from "yup";
import { toast } from "@opal/layouts";
import {
  createDocumentSet,
  updateDocumentSet,
  DocumentSetCreationRequest,
} from "./lib";
import {
  ConnectorStatus,
  DocumentSetSummary,
  FederatedConnectorConfig,
  Permission,
} from "@/lib/types";
import { TextFormField } from "@/components/Field";
import { Button } from "@opal/components";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import React, { useEffect, useState } from "react";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";
import { NonSelectableConnectors } from "@/components/NonSelectableConnectors";
import { FederatedConnectorSelector } from "@/components/FederatedConnectorSelector";
import { useFederatedConnectors } from "@/lib/hooks";

interface SetCreationPopupProps {
  ccPairs: ConnectorStatus<any, any>[];
  onClose: () => void;
  existingDocumentSet?: DocumentSetSummary;
}

export const DocumentSetCreationForm = ({
  ccPairs,
  onClose,
  existingDocumentSet,
}: SetCreationPopupProps) => {
  const t = useTranslations("admin.documents");
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const isUpdate = existingDocumentSet !== undefined;
  const [localCcPairs, setLocalCcPairs] = useState(ccPairs);
  const { user } = useUser();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_DOCUMENT_SETS
  );
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
            name: Yup.string().required(t("sets.form.name.required")),
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
            t("sets.form.connectors.required"),
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
            toast.success(
              isUpdate
                ? t("sets.form.updated.toast")
                : t("sets.form.created.toast")
            );
            await Promise.all([
              mutate(SWR_KEYS.documentSets),
              mutate(SWR_KEYS.documentSetsEditable),
            ]);
            onClose();
          } else {
            const errorMsg = await response.text();
            toast.error(
              isUpdate
                ? t("sets.form.updateFailed.toast", { detail: errorMsg })
                : t("sets.form.createFailed.toast", { detail: errorMsg })
            );
          }
        }}
      >
        {(props) => {
          // Only a scoped manager is restricted to connectors in their groups; a
          // global MANAGE_DOCUMENT_SETS holder is org-wide and sees them all.
          const visibleCcPairs = isScopedManager
            ? localCcPairs.filter(
                (ccPair) =>
                  ccPair.access_type === "public" ||
                  (ccPair.groups.length > 0 &&
                    props.values.groups.every((group) =>
                      ccPair.groups.includes(group)
                    ))
              )
            : localCcPairs;

          const nonVisibleCcPairs = isScopedManager
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
          if (isScopedManager) {
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
                  label={t("sets.form.name.label")}
                  placeholder={t("sets.form.name.placeholder")}
                />
                <TextFormField
                  name="description"
                  label={t("sets.form.description.label")}
                  placeholder={t("sets.form.description.placeholder")}
                  optional={true}
                />

                {businessTier && (
                  <IsPublicGroupSelector
                    formikProps={props}
                    objectName="document set"
                    isGlobalHolder={isGlobalHolder}
                  />
                )}
              </div>

              <div className="my-6 border-t border-border-02" />

              <div className="space-y-6">
                {isScopedManager ? (
                  <>
                    <ConnectorMultiSelect
                      name="cc_pair_ids"
                      label={t("sets.form.scopedConnectors.label", {
                        count: props.values.groups.length,
                      })}
                      connectors={visibleCcPairs}
                      selectedIds={props.values.cc_pair_ids}
                      onChange={(selectedIds) => {
                        props.setFieldValue("cc_pair_ids", selectedIds);
                      }}
                      placeholder={t("sets.form.connectors.placeholder")}
                    />

                    <NonSelectableConnectors
                      connectors={nonVisibleCcPairs}
                      title={t("sets.form.unavailableConnectors.title", {
                        count: props.values.groups.length,
                      })}
                      description={t(
                        "sets.form.unavailableConnectors.description"
                      )}
                    />
                  </>
                ) : (
                  <ConnectorMultiSelect
                    name="cc_pair_ids"
                    label={t("sets.form.connectors.label")}
                    connectors={visibleCcPairs}
                    selectedIds={props.values.cc_pair_ids}
                    onChange={(selectedIds) => {
                      props.setFieldValue("cc_pair_ids", selectedIds);
                    }}
                    placeholder={t("sets.form.connectors.placeholder")}
                  />
                )}

                {/* Federated Connectors Section */}
                {federatedConnectors && federatedConnectors.length > 0 && (
                  <>
                    <div className="my-4 border-t border-border-02" />
                    <FederatedConnectorSelector
                      name="federated_connectors"
                      label={t("sets.form.federatedConnectors.label")}
                      federatedConnectors={federatedConnectors}
                      selectedConfigs={props.values.federated_connectors}
                      onChange={(selectedConfigs) => {
                        props.setFieldValue(
                          "federated_connectors",
                          selectedConfigs
                        );
                      }}
                      placeholder={t(
                        "sets.form.federatedConnectors.placeholder"
                      )}
                    />
                  </>
                )}
              </div>

              <div className="flex mt-6 pt-4 border-t border-border-02">
                <div className="mx-auto w-56">
                  <Button
                    type="submit"
                    disabled={props.isSubmitting}
                    width="full"
                  >
                    {isUpdate
                      ? t("sets.form.submitButton.updateLabel")
                      : t("sets.form.submitButton.createLabel")}
                  </Button>
                </div>
              </div>
            </Form>
          );
        }}
      </Formik>
    </div>
  );
};
