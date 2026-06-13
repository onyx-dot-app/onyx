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
import { Tier } from "@/interfaces/settings";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import React, { useEffect, useState } from "react";
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
  const businessTier = useTierAtLeast(Tier.BUSINESS);
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
            name: Yup.string().required("请输入文档集名称"),
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
            "请选择至少一个连接器（普通或联合连接器）",
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
                ? "文档集已更新！"
                : "文档集已创建！"
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
                ? `更新文档集失败 - ${errorMsg}`
                : `创建文档集失败 - ${errorMsg}`
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
                  label="名称："
                  placeholder="为文档集命名"
                />
                <TextFormField
                  name="description"
                  label="描述："
                  placeholder="描述这个文档集代表的内容"
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
                      label={`可用于${
                        userGroups && userGroups.length > 1
                          ? "所选用户组"
                          : "你管理的用户组"
                      }`}
                      connectors={visibleCcPairs}
                      selectedIds={props.values.cc_pair_ids}
                      onChange={(selectedIds) => {
                        props.setFieldValue("cc_pair_ids", selectedIds);
                      }}
                      placeholder="搜索连接器..."
                    />

                    <NonSelectableConnectors
                      connectors={nonVisibleCcPairs}
                      title={`不可用于${
                        userGroups && userGroups.length > 1
                          ? "你所选的用户组"
                          : "你管理的用户组"
                      }`}
                      description="只有直接分配给目标用户组的连接器才可用于此文档集。"
                    />
                  </>
                ) : (
                  <ConnectorMultiSelect
                    name="cc_pair_ids"
                    label="选择连接器"
                    connectors={visibleCcPairs}
                    selectedIds={props.values.cc_pair_ids}
                    onChange={(selectedIds) => {
                      props.setFieldValue("cc_pair_ids", selectedIds);
                    }}
                    placeholder="搜索连接器..."
                  />
                )}

                {/* Federated Connectors Section */}
                {federatedConnectors && federatedConnectors.length > 0 && (
                  <>
                    <div className="my-4 border-t border-border-02" />
                    <FederatedConnectorSelector
                      name="federated_connectors"
                      label="联合连接器"
                      federatedConnectors={federatedConnectors}
                      selectedConfigs={props.values.federated_connectors}
                      onChange={(selectedConfigs) => {
                        props.setFieldValue(
                          "federated_connectors",
                          selectedConfigs
                        );
                      }}
                      placeholder="搜索联合连接器..."
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
                  {isUpdate ? "更新文档集" : "创建文档集"}
                </Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </div>
  );
};
