"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

import { Form, Formik } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  createDocumentSet,
  updateDocumentSet,
  DocumentSetCreationRequest,
} from "./lib";
import { ConnectorStatus, DocumentSet, UserGroup, UserRole } from "@/lib/types";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import React, { useEffect, useState } from "react";
import { useUser } from "@/components/user/UserProvider";
import { ConnectorMultiSelect } from "@/components/ConnectorMultiSelect";
import { NonSelectableConnectors } from "@/components/NonSelectableConnectors";

interface SetCreationPopupProps {
  ccPairs: ConnectorStatus<any, any>[];
  userGroups: UserGroup[] | undefined;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  existingDocumentSet?: DocumentSet;
}

export const DocumentSetCreationForm = ({
  ccPairs,
  userGroups,
  onClose,
  setPopup,
  existingDocumentSet,
}: SetCreationPopupProps) => {
  const { t } = useTranslation();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const isUpdate = existingDocumentSet !== undefined;
  const [localCcPairs, setLocalCcPairs] = useState(ccPairs);
  const { user } = useUser();

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
            existingDocumentSet?.cc_pair_descriptors.map(
              (ccPairDescriptor) => ccPairDescriptor.id
            ) ?? [],
          is_public: existingDocumentSet?.is_public ?? true,
          users: existingDocumentSet?.users ?? [],
          groups: existingDocumentSet?.groups ?? [],
        }}
        validationSchema={Yup.object().shape({
          name: Yup.string().required(t(k.PLEASE_ENTER_NAME_FOR_SET)),
          description: Yup.string().optional(),
          cc_pair_ids: Yup.array()
            .of(Yup.number().required())
            .required(t(k.PLEASE_SELECT_AT_LEAST_ONE_CONNECTOR)),
        })}
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
                ? t(k.SUCCESSFULLY_UPDATED_DOCUMENT)
                : t(k.SUCCESSFULLY_CREATED_DOCUMENT),

              type: "success",
            });
            onClose();
          } else {
            const errorMsg = await response.text();
            setPopup({
              message: isUpdate
                ? `${t(k.ERROR_UPDATING_DOCUMENT_SET)} ${errorMsg}`
                : `${t(k.ERROR_CREATING_DOCUMENT_SET)} ${errorMsg}`,
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
                  label={t(k.NAME_LABEL)}
                  placeholder={t(k.NAME_PLACEHOLDER)}
                  disabled={isUpdate}
                  autoCompleteDisabled={true}
                />

                <TextFormField
                  name="description"
                  label={t(k.DESCRIPTION_LABEL)}
                  placeholder={t(k.DESCRIPTION_PLACEHOLDER)}
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

              <Separator className="my-6" />

              <div className="space-y-6">
                {user?.role === UserRole.CURATOR ? (
                  <>
                    <ConnectorMultiSelect
                      name="cc_pair_ids"
                      label={`${t(k.CONNECTORS_AVAILABLE_TO_GROUP)} ${
                        userGroups && userGroups.length > 1
                          ? t(k.THE_SELECTED_GROUP)
                          : t(k.THE_GROUP_YOU_CURATE)
                      }`}
                      connectors={visibleCcPairs}
                      selectedIds={props.values.cc_pair_ids}
                      onChange={(selectedIds) => {
                        props.setFieldValue(t(k.CC_PAIR_IDS), selectedIds);
                      }}
                      placeholder={t(k.SEARCH_CONNECTORS_PLACEHOLDER)}
                    />

                    <NonSelectableConnectors
                      connectors={nonVisibleCcPairs}
                      title={`${t(k.CONNECTORS_NOT_AVAILABLE_TO_GROUP)} ${
                        userGroups && userGroups.length > 1
                          ? `${t(k.GROUP)}${
                              props.values.groups.length > 1 ? t(k.S) : ""
                            } ${t(k.YOU_HAVE_SELECTED1)}`
                          : t(k.GROUP_YOU_CURATE)
                      }`}
                      description={t(k.CONNECTORS_NOT_AVAILABLE_DESCRIPTION)}
                    />
                  </>
                ) : (
                  <ConnectorMultiSelect
                    name="cc_pair_ids"
                    label={t(k.SELECT_CONNECTORS_LABEL)}
                    connectors={visibleCcPairs}
                    selectedIds={props.values.cc_pair_ids}
                    onChange={(selectedIds) => {
                      props.setFieldValue(t(k.CC_PAIR_IDS), selectedIds);
                    }}
                    placeholder={t(k.SEARCH_CONNECTORS_PLACEHOLDER)}
                  />
                )}
              </div>

              <div className="flex mt-6 pt-4 border-t border-neutral-200">
                <Button
                  type="submit"
                  variant="submit"
                  disabled={props.isSubmitting}
                  className="w-56 mx-auto py-1.5 h-auto text-sm"
                >
                  {isUpdate
                    ? t(k.UPDATE_DOCUMENT_SET)
                    : t(k.CREATE_DOCUMENT_SET1)}
                </Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </div>
  );
};
