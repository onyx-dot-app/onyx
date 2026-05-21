import { Formik, Form } from "formik";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { SvgEdit } from "@opal/icons";

export interface EditPropertyModalProps {
  propertyTitle: string;
  propertyDetails?: string;
  propertyName: string;
  propertyValue: string;
  validationSchema: object;
  onClose: () => void;
  onSubmit: (propertyName: string, propertyValue: string) => Promise<void>;
}

export default function EditPropertyModal({
  propertyTitle,
  propertyDetails,
  propertyName,
  propertyValue,
  validationSchema,
  onClose,
  onSubmit,
}: EditPropertyModalProps) {
  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgEdit}
          title={`Edit ${propertyTitle}`}
          onClose={onClose}
        />
        <Formik
          initialValues={{
            propertyName,
            propertyValue,
          }}
          validationSchema={validationSchema}
          onSubmit={async (values, { setSubmitting }) => {
            try {
              await onSubmit(values.propertyName, values.propertyValue);
              onClose();
            } finally {
              setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, isValid, values }) => (
            <Form className="w-full">
              <Modal.Body>
                <InputVertical
                  title={propertyDetails ?? ""}
                  withLabel="propertyValue"
                >
                  <InputTypeInField
                    name="propertyValue"
                    placeholder="Property value"
                  />
                </InputVertical>
              </Modal.Body>
              <Modal.Footer>
                <Button
                  disabled={
                    isSubmitting ||
                    !isValid ||
                    values.propertyValue === propertyValue
                  }
                  type="submit"
                >
                  {isSubmitting ? "Updating..." : "Update property"}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
