"use client";

import { ArrayHelpers, FieldArray, Form, Formik } from "formik";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  createDocumentSet,
  updateDocumentSet,
  DocumentSetCreationRequest,
} from "./lib";
import { ConnectorStatus, DocumentSet, UserGroup, UserRole } from "@/lib/types";
import { TextFormField } from "@/components/admin/connectors/Field";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { Separator } from "@/components/ui/separator";
import { Button } from "@/components/ui/button";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { IsPublicGroupSelector } from "@/components/IsPublicGroupSelector";
import React, { useEffect, useState } from "react";
import { useUser } from "@/components/user/UserProvider";

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
    <div>
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
          name: Yup.string().required("Please enter a name for the set"),
          description: Yup.string().optional(),
          cc_pair_ids: Yup.array()
            .of(Yup.number().required())
            .required("Please select at least one connector"),
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
          return (
            <Form>
              <TextFormField
                name="name"
                label="Name:"
                placeholder="A name for the document set"
                disabled={isUpdate}
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

              <Separator />

              {user?.role === UserRole.CURATOR ? (
                <>
                  <div className="flex flex-col gap-y-1">
                    <h2 className="mb-1 font-medium text-base">
                      These are the connectors available to{" "}
                      {userGroups && userGroups.length > 1
                        ? "the selected group"
                        : "the group you curate"}
                      :
                    </h2>

                    <p className="mb-text-sm">
                      All documents indexed by these selected connectors will be
                      a part of this document set.
                    </p>
                    <FieldArray
                      name="cc_pair_ids"
                      render={(arrayHelpers: ArrayHelpers) => {
                        // Filter visible cc pairs
                        const visibleCcPairs = localCcPairs.filter(
                          (ccPair) =>
                            ccPair.access_type === "public" ||
                            (ccPair.groups.length > 0 &&
                              props.values.groups.every((group) =>
                                ccPair.groups.includes(group)
                              ))
                        );

                        // Deselect filtered out cc pairs
                        const visibleCcPairIds = visibleCcPairs.map(
                          (ccPair) => ccPair.cc_pair_id
                        );
                        props.values.cc_pair_ids =
                          props.values.cc_pair_ids.filter((id) =>
                            visibleCcPairIds.includes(id)
                          );

                        return (
                          <div className="mb-3 flex gap-2 flex-wrap">
                            {visibleCcPairs.map((ccPair) => {
                              const ind = props.values.cc_pair_ids.indexOf(
                                ccPair.cc_pair_id
                              );
                              const isSelected = ind !== -1;
                              return (
                                <div
                                  key={`${ccPair.connector.id}-${ccPair.credential.id}`}
                                  className={
                                    `
                                  px-3 
                                  py-1
                                  rounded-lg 
                                  border
                                  border-border 
                                  w-fit 
                                  flex 
                                  cursor-pointer ` +
                                    (isSelected
                                      ? " bg-background-strong"
                                      : " hover:bg-hover")
                                  }
                                  onClick={() => {
                                    if (isSelected) {
                                      arrayHelpers.remove(ind);
                                    } else {
                                      arrayHelpers.push(ccPair.cc_pair_id);
                                    }
                                  }}
                                >
                                  <div className="my-auto">
                                    <ConnectorTitle
                                      connector={ccPair.connector}
                                      ccPairId={ccPair.cc_pair_id}
                                      ccPairName={ccPair.name}
                                      isLink={false}
                                      showMetadata={false}
                                    />
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        );
                      }}
                    />
                  </div>

                  <div>
                    <FieldArray
                      name="cc_pair_ids"
                      render={() => {
                        // Filter non-visible cc pairs
                        const nonVisibleCcPairs = localCcPairs.filter(
                          (ccPair) =>
                            !(ccPair.access_type === "public") &&
                            (ccPair.groups.length === 0 ||
                              !props.values.groups.every((group) =>
                                ccPair.groups.includes(group)
                              ))
                        );

                        return nonVisibleCcPairs.length > 0 ? (
                          <>
                            <Separator />
                            <h2 className="mb-1 font-medium text-base">
                              These connectors are not available to the{" "}
                              {userGroups && userGroups.length > 1
                                ? `group${
                                    props.values.groups.length > 1 ? "s" : ""
                                  } you have selected`
                                : "group you curate"}
                              :
                            </h2>
                            <p className="mb-3 text-sm">
                              Only connectors that are directly assigned to the
                              group you are trying to add the document set to
                              will be available.
                            </p>
                            <div className="mb-3 flex gap-2 flex-wrap">
                              {nonVisibleCcPairs.map((ccPair) => (
                                <div
                                  key={`${ccPair.connector.id}-${ccPair.credential.id}`}
                                  className="px-3 py-1 rounded-lg border border-non-selectable-border w-fit flex cursor-not-allowed"
                                >
                                  <div className="my-auto">
                                    <ConnectorTitle
                                      connector={ccPair.connector}
                                      ccPairId={ccPair.cc_pair_id}
                                      ccPairName={ccPair.name}
                                      isLink={false}
                                      showMetadata={false}
                                    />
                                  </div>
                                </div>
                              ))}
                            </div>
                          </>
                        ) : null;
                      }}
                    />
                  </div>
                </>
              ) : (
                <div>
                  <h2 className="mb-1 font-medium text-base">
                    Pick your connectors:
                  </h2>
                  <p className="mb-3 text-xs">
                    All documents indexed by the selected connectors will be a
                    part of this document set.
                  </p>
                  <FieldArray
                    name="cc_pair_ids"
                    render={(arrayHelpers: ArrayHelpers) => (
                      <div className="mb-3 flex gap-2 flex-wrap">
                        {ccPairs.map((ccPair) => {
                          const ind = props.values.cc_pair_ids.indexOf(
                            ccPair.cc_pair_id
                          );
                          const isSelected = ind !== -1;
                          return (
                            <div
                              key={`${ccPair.connector.id}-${ccPair.credential.id}`}
                              className={
                                `
                              px-3 
                              py-1
                              rounded-lg 
                              border
                              border-border 
                              w-fit 
                              flex 
                              cursor-pointer ` +
                                (isSelected
                                  ? " bg-background-strong"
                                  : " hover:bg-hover")
                              }
                              onClick={() => {
                                if (isSelected) {
                                  arrayHelpers.remove(ind);
                                } else {
                                  arrayHelpers.push(ccPair.cc_pair_id);
                                }
                              }}
                            >
                              <div className="my-auto">
                                <ConnectorTitle
                                  connector={ccPair.connector}
                                  ccPairId={ccPair.cc_pair_id}
                                  ccPairName={ccPair.name}
                                  isLink={false}
                                  showMetadata={false}
                                />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  />
                </div>
              )}

              <div className="flex mt-6">
                <Button
                  type="submit"
                  variant="submit"
                  disabled={props.isSubmitting}
                  className="w-64 mx-auto"
                >
                  {isUpdate ? "Update!" : "Create!"}
                </Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </div>
  );
};
