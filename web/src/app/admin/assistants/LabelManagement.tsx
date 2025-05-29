"use client";

import React from "react";
import { Button } from "@/components/ui/button";
import { SubLabel, TextFormField } from "@/components/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useLabels } from "@/lib/hooks";
import { PersonaLabel } from "./interfaces";
import { Form, Formik, FormikHelpers } from "formik";
import Title from "@/components/ui/title";

interface FormValues {
  newLabelName: string;
  editLabelId: number | null;
  editLabelName: string;
}

export default function LabelManagement() {
  const { labels, createLabel, updateLabel, deleteLabel } = useLabels();
  const { setPopup, popup } = usePopup();

  if (!labels) return null;

  const handleSubmit = async (
    values: FormValues,
    { setSubmitting, resetForm }: FormikHelpers<FormValues>
  ) => {
    if (values.newLabelName.trim()) {
      const response = await createLabel(values.newLabelName.trim());
      if (response.ok) {
        setPopup({
          message: `Label "${values.newLabelName}" created successfully`,
          type: "success",
        });
        resetForm();
      } else {
        const errorMsg = (await response.json()).detail;
        setPopup({
          message: `Failed to create label - ${errorMsg}`,
          type: "error",
        });
      }
    }
    setSubmitting(false);
  };

  return (
    <div>
      {popup}
      <div className="max-w-4xl">
        <div className="flex gap-x-2 items-center">
          <Title size="lg">Manage Labels</Title>
        </div>

        <Formik<FormValues>
          initialValues={{
            newLabelName: "",
            editLabelId: null,
            editLabelName: "",
          }}
          onSubmit={handleSubmit}
        >
          {({ values, setFieldValue, isSubmitting }) => (
            <Form>
              <div className="flex flex-col gap-4 mt-4 mb-6">
                <div className="flex flex-col">
                  <Title className="text-lg">Create New Label</Title>
                  <SubLabel>
                    Labels are used to categorize personas. You can create a new
                    label by entering a name below.
                  </SubLabel>
                </div>
                <div className="max-w-3xl w-full justify-start flex gap-4 items-end">
                  <TextFormField
                    width="max-w-xs"
                    fontSize="sm"
                    name="newLabelName"
                    label="Label Name"
                  />
                  <Button type="submit" disabled={isSubmitting}>
                    Create
                  </Button>
                </div>
              </div>

              <div className="grid grid-cols-1 w-full gap-4">
                <div className="flex flex-col">
                  <Title className="text-lg">Edit Labels</Title>
                  <SubLabel>
                    You can edit the name of a label by clicking on the label
                    name and entering a new name.
                  </SubLabel>
                </div>

                {labels.map((label: PersonaLabel) => (
                  <div key={label.id} className="flex w-full  gap-4 items-end">
                    <TextFormField
                      fontSize="sm"
                      width="w-full max-w-xs"
                      name={`editLabelName_${label.id}`}
                      label="Label Name"
                      onChange={(e) => {
                        setFieldValue("editLabelId", label.id);
                        setFieldValue("editLabelName", e.target.value);
                      }}
                    />
                    <div className="flex gap-2">
                      {values.editLabelId === label.id ? (
                        <>
                          <Button
                            onClick={async () => {
                              const updatedName =
                                values.editLabelName || label.name;
                              const response = await updateLabel(
                                label.id,
                                updatedName
                              );
                              if (response.ok) {
                                setPopup({
                                  message: `Label "${updatedName}" updated successfully`,
                                  type: "success",
                                });
                                setFieldValue("editLabelId", null);
                                setFieldValue("editLabelName", "");
                              } else {
                                setPopup({
                                  message: `Failed to update label - ${await response.text()}`,
                                  type: "error",
                                });
                              }
                            }}
                          >
                            Save
                          </Button>
                          <Button
                            variant="outline"
                            onClick={() => {
                              setFieldValue("editLabelId", null);
                              setFieldValue("editLabelName", "");
                            }}
                          >
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          variant="destructive"
                          onClick={async () => {
                            const response = await deleteLabel(label.id);
                            if (response.ok) {
                              setPopup({
                                message: `Label "${label.name}" deleted successfully`,
                                type: "success",
                              });
                            } else {
                              setPopup({
                                message: `Failed to delete label - ${await response.text()}`,
                                type: "error",
                              });
                            }
                          }}
                        >
                          Delete
                        </Button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </Form>
          )}
        </Formik>
      </div>
    </div>
  );
}
