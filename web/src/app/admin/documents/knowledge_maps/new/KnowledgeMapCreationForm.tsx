import i18n from "@/i18n/init";
import k from "../../../../../i18n/keys";
import { ArrayHelpers, FieldArray, Form, Formik } from "formik";
import { useEffect, useState } from "react";
import * as Yup from "yup";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConnectorIndexingStatus, DocumentSet, UserGroup } from "@/lib/types";
import {
  BooleanFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import {
  Button,
  Divider,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Text,
  Title,
} from "@tremor/react";
import { EE_ENABLED } from "@/lib/constants";
import { FiUsers } from "react-icons/fi";
import { DocumentSetSelectable } from "@/components/documentSet/DocumentSetSelectable";
import { DefaultDropdown } from "@/components/Dropdown";
import {
  createKnowledgeMap,
  deleteKnowledgeMap,
  generateAnswers,
  KnowledgeMapCreationRequest,
  KnowledgeMapUpdateRequest,
  updateKnowledgeMap,
} from "../lib";
import { DeleteButton } from "@/components/DeleteButton";
import { numToDisplay } from "../../feedback/constants";
import { EditRow } from "../editRow";
import { refreshKnowledgeMaps } from "../hooks";
import page from "../page";

interface SetCreationPopupProps {
  ccPairs: DocumentSet[];
  userGroups: UserGroup[] | undefined;
  onClose: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
  existingDocumentSet?: KnowledgeMapCreationRequest;
}

export const KnowledgeMapCreationForm = ({
  ccPairs,
  userGroups,
  onClose,
  setPopup,
  existingDocumentSet,
}: SetCreationPopupProps) => {
  const isUpdate = existingDocumentSet !== undefined;
  const [selectedDoc, setSelectedDoc] = useState<number | null>(
    existingDocumentSet ? existingDocumentSet.document_set_id : null
  );
  return (
    <div>
      <Formik
        initialValues={{
          name: existingDocumentSet ? existingDocumentSet.name : "",
          description: existingDocumentSet
            ? existingDocumentSet.description
            : "",
          flowiseId: existingDocumentSet
            ? existingDocumentSet.flowise_pipeline_id
            : "",
        }}
        validationSchema={Yup.object().shape({
          name: Yup.string().required(i18n.t(k.ENTER_KNOWLEDGE_MAP_NAME)),
          description: Yup.string().required(
            i18n.t(k.ENTER_DESCRIPTION_FOR_SET)
          ),
        })}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);
          const processedValues = {
            ...values,
            flowise_pipeline_id: values.flowiseId,
            document_set_id: selectedDoc,
          };
          let response;
          if (isUpdate) {
            response = await updateKnowledgeMap({
              id: existingDocumentSet.id,
              ...processedValues,
            } as unknown as KnowledgeMapUpdateRequest);
          } else {
            response = await createKnowledgeMap(
              processedValues as unknown as KnowledgeMapCreationRequest
            );
          }
          formikHelpers.setSubmitting(false);
          if (response.ok) {
            setPopup({
              message: isUpdate
                ? i18n.t(k.KNOWLEDGE_MAP_UPDATED_SUCCESS)
                : i18n.t(k.KNOWLEDGE_MAP_CREATED_SUCCESS),
              type: "success",
            });
            const responseData = await response.json();
            generateAnswers(responseData.id);
            onClose();
          } else {
            const errorMsg = await response.text();
            setPopup({
              message: isUpdate
                ? `${i18n.t(k.KNOWLEDGE_MAP_UPDATE_ERROR)} ${errorMsg}`
                : `${i18n.t(k.KNOWLEDGE_MAP_CREATE_ERROR)} ${errorMsg}`,
              type: "error",
            });
          }
        }}
      >
        {({ isSubmitting, values }) => (
          <Form>
            <TextFormField
              name="name"
              label={i18n.t(k.NAME_LABEL)}
              placeholder={i18n.t(k.KNOWLEDGE_MAP_NAME_PLACEHOLDER)}
              autoCompleteDisabled={true}
            />
            <TextFormField
              name="description"
              label={i18n.t(k.DESCRIPTION_LABEL)}
              placeholder={i18n.t(k.KNOWLEDGE_MAP_DESCRIPTION_PLACEHOLDER)}
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="flowiseId"
              label={i18n.t(k.FLOWISE_PIPELINE_LABEL)}
              placeholder={i18n.t(k.FLOWISE_PIPELINE_PLACEHOLDER)}
              autoCompleteDisabled={true}
            />

            <h2 className="mb-1 font-medium text-base">
              {i18n.t(k.SELECT_DOCUMENT_SET)}
            </h2>
            <p className="mb-3 text-xs">
              {i18n.t(k.KNOWLEDGE_MAP_FORMATION_DESCRIPTION)}
            </p>
            <FieldArray
              name="cc_pair_ids"
              render={(arrayHelpers: ArrayHelpers) => (
                <div className="mb-3 flex gap-2 flex-wrap">
                  {ccPairs.map((ccPair) => {
                    //@ts-ignore

                    let isSelected = selectedDoc === ccPair.id;
                    return (
                      <div
                        key={`${ccPair.id}-${ccPair.id}`}
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
                      >
                        <div className="my-auto">
                          <DocumentSetSelectable
                            key={ccPair.id}
                            documentSet={ccPair}
                            isSelected={isSelected}
                            onSelect={() => {
                              if (isSelected) {
                                setSelectedDoc(null);
                              } else {
                                setSelectedDoc(ccPair.id);
                              }
                            }}
                          ></DocumentSetSelectable>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            />

            <div className="flex mt-6">
              <Button
                type="submit"
                disabled={isSubmitting}
                className="w-64 mx-auto"
              >
                {isUpdate ? i18n.t(k.UPDATE) : i18n.t(k.CREATE)}
              </Button>
            </div>
          </Form>
        )}
      </Formik>

      {isUpdate && (
        <div>
          <Title>{i18n.t(k.KNOWLEDGE_MAP_VIEW_EDIT)}</Title>
          <Table className="overflow-visible mt-2">
            <TableHead>
              <TableRow>
                <TableHeaderCell>{i18n.t(k.TOPIC_NAME)}</TableHeaderCell>
                <TableHeaderCell>
                  {i18n.t(k.TOPIC_DESCRIPTION_HEADER)}
                </TableHeaderCell>
                <TableHeaderCell>
                  {i18n.t(k.QUERY_EXAMPLES_HEADER)}
                </TableHeaderCell>
                <TableHeaderCell>key_json</TableHeaderCell>
                <TableHeaderCell>{i18n.t(k.SOURCE_HEADER)}</TableHeaderCell>
                <TableHeaderCell>{i18n.t(k.SELECTION_HEADER)}</TableHeaderCell>
                <TableHeaderCell>{i18n.t(k.KNOWLEDGE_HEADER)}</TableHeaderCell>
                <TableHeaderCell>{i18n.t(k.EXTRACTION_HEADER)}</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {existingDocumentSet?.answers?.map((answer) => {
                return (
                  <TableRow key={answer.id}>
                    <TableCell className="whitespace-normal break-all">
                      {answer.topic}
                    </TableCell>
                    <TableCell>{answer.topic}</TableCell>
                    <TableCell></TableCell>
                    <TableCell></TableCell>
                    <TableCell>{answer.document_id}</TableCell>
                    <TableCell>
                      <input
                        type="checkbox"
                        className="mx-3 px-5 w-3.5 h-3.5 my-auto"
                      />
                    </TableCell>
                    <TableCell>{answer.knowledge_map_id}</TableCell>
                    <TableCell>
                      <input
                        type="checkbox"
                        className="mx-3 px-5 w-3.5 h-3.5 my-auto"
                      />
                    </TableCell>
                    <TableCell></TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>

          <div className="flex mt-6">
            <Button
              type="submit"
              className="w-64 mx-auto"
              onClick={() => {
                generateAnswers(existingDocumentSet.id);
              }}
            >
              {i18n.t(k.EXTRACT_BUTTON)}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
