import React from "react";
import { Formik, Form } from "formik";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { TextFormField } from "@/components/Field";
import { EditIcon } from "../icons/icons";

const EditPropertyModal = ({
  propertyTitle, // A friendly title to be displayed for the property
  propertyDetails, // a helpful description of the property to be displayed, (Valid ranges, units, etc)
  propertyName, // the programmatic property name
  propertyValue, // the programmatic property value (current)
  validationSchema, // Allow custom Yup schemas ... set on "propertyValue"
  onClose,
  onSubmit,
}: {
  propertyTitle: string;
  propertyDetails?: string;
  propertyName: string;
  propertyValue: string;
  validationSchema: any;
  onClose: () => void;
  onSubmit: (propertyName: string, propertyValue: string) => Promise<void>;
}) => {
  return (
    <Modal onOutsideClick={onClose} width="w-full max-w-xl">
      <Formik
        initialValues={{
          propertyName: propertyName,
          propertyValue: propertyValue,
        }}
        validationSchema={validationSchema}
        onSubmit={(values) => {
          onSubmit(values.propertyName, values.propertyValue);
          onClose();
        }}
      >
        {({ isSubmitting, isValid, values }) => (
          <Form className="items-stretch">
            <h2 className="text-2xl text-text-darker font-bold mb-3 flex items-center">
              <EditIcon size={20} className="mr-2" />
              Edit {propertyTitle}
            </h2>

            <TextFormField
              vertical
              label={propertyDetails || ""}
              name="propertyValue"
              placeholder="Property value"
            />

            <div className="mt-6">
              <Button
                type="submit"
                disabled={
                  isSubmitting ||
                  !isValid ||
                  values.propertyValue === propertyValue
                }
              >
                {isSubmitting ? "Updating..." : "Update property"}
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </Modal>
  );
};

export default EditPropertyModal;
