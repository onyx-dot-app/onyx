"use client";

import { Form, Formik } from "formik";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import * as Yup from "yup";
import { toast } from "@/hooks/useToast";
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
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import React, { useEffect, useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import i18n from "@/lib/i18n";
import { useUser } from "@/providers/UserProvider";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";
import { NonSelectableConnectors } from "@/components/NonSelectableConnectors";
import { FederatedConnectorSelector } from "@/components/FederatedConnectorSelector";
import { useFederatedConnectors } from "@/lib/hooks";

interface SetCreationPopupProps {
  ccPairs: ConnectorStatus<any, any>[];
  userGroups: UserGroup[] | undefined;
  onClose: () => void;
  existingDocumentSet?: DocumentSetSummary;
}

export const DocumentSetCreationForm = ({
  ccPairs,
  userGroups,
  onClose,
  existingDocumentSet,
}: SetCreationPopupProps) => {
  const { t } = useTranslation();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const isUpdate = existingDocumentSet !== undefined;
  const [localCcPairs, setLocalCcPairs] = useState(ccPairs);
  const { user } = useUser();
  const { data: federatedConnectors } = useFederatedConnectors();

  const validationSchema = useMemo(
    () =>
      Yup.object()
        .shape({
          name: Yup.string().required(
            i18n.t("admin.document_sets.name_required")
          ),
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
          i18n.t("admin.document_sets.connectors_required"),
          function (values) {
            const hasRegularConnectors =
              values.cc_pair_ids && values.cc_pair_ids.length > 0;
            const hasFederatedConnectors =
              values.federated_connectors &&
              values.federated_connectors.length > 0;
            return hasRegularConnectors || hasFederatedConnectors;
          }
        ),
    []
  );

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
        validationSchema={validationSchema}
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
                ? t("admin.document_sets.update_success")
                : t("admin.document_sets.create_success")
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
                ? t("admin.document_sets.update_error", { error: errorMsg })
                : t("admin.document_sets.create_error", { error: errorMsg })
            );
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
                  label={t("admin.document_sets.name_label")}
                  placeholder={t("admin.document_sets.name_placeholder")}
                />
                <TextFormField
                  name="description"
                  label={t("admin.document_sets.description_label")}
                  placeholder={t("admin.document_sets.description_placeholder")}
                  optional={true}
                />

                {businessTier && (
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
                      label={
                        userGroups && userGroups.length > 1
                          ? t("admin.document_sets.connectors_available_selected_group")
                          : t("admin.document_sets.connectors_available_curate_group")
                      }
                      connectors={visibleCcPairs}
                      selectedIds={props.values.cc_pair_ids}
                      onChange={(selectedIds) => {
                        props.setFieldValue("cc_pair_ids", selectedIds);
                      }}
                      placeholder={t("admin.document_sets.search_connectors")}
                    />

                    <NonSelectableConnectors
                      connectors={nonVisibleCcPairs}
                      title={
                        userGroups && userGroups.length > 1
                          ? t("admin.document_sets.connectors_not_available_groups", {
                              count: props.values.groups.length,
                            })
                          : t("admin.document_sets.connectors_not_available_group")
                      }
                      description={t("admin.document_sets.connectors_curator_hint")}
                    />
                  </>
                ) : (
                  <ConnectorMultiSelect
                    name="cc_pair_ids"
                    label={t("admin.document_sets.pick_connectors")}
                    connectors={visibleCcPairs}
                    selectedIds={props.values.cc_pair_ids}
                    onChange={(selectedIds) => {
                      props.setFieldValue("cc_pair_ids", selectedIds);
                    }}
                    placeholder={t("admin.document_sets.search_connectors")}
                  />
                )}

                {/* Federated Connectors Section */}
                {federatedConnectors && federatedConnectors.length > 0 && (
                  <>
                    <div className="my-4 border-t border-border-02" />
                    <FederatedConnectorSelector
                      name="federated_connectors"
                      label={t("admin.document_sets.federated_connectors_label")}
                      federatedConnectors={federatedConnectors}
                      selectedConfigs={props.values.federated_connectors}
                      onChange={(selectedConfigs) => {
                        props.setFieldValue(
                          "federated_connectors",
                          selectedConfigs
                        );
                      }}
                      placeholder={t(
                        "admin.document_sets.search_federated_connectors"
                      )}
                    />
                  </>
                )}
              </div>

              <div className="flex mt-6 pt-4 border-t border-border-02">
                {/* TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved */}
                <Button
                  type="submit"
                  disabled={props.isSubmitting}
                  className="w-56 mx-auto"
                  primary
                >
                  {isUpdate
                    ? t("admin.document_sets.update")
                    : t("admin.document_sets.create")}
                </Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </div>
  );
};
