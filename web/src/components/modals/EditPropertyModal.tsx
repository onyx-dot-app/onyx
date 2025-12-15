import { Formik, Form } from "formik";
import Modal from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import { TextFormField } from "@/components/Field";
import SvgEdit from "@/icons/edit";

export interface EditPropertyModalProps {
  propertyTitle: string;
  propertyDetails?: string;
  propertyName: string;
  propertyValue: string;
  validationSchema: any;
  onClose: () => void;
  onSubmit: (propertyName: string, propertyValue: string) => Promise<void>;
}

export default function EditPropertyModal({
  propertyTitle, // A friendly title to be displayed for the property
  propertyDetails, // a helpful description of the property to be displayed, (Valid ranges, units, etc)
  propertyName, // the programmatic property name
  propertyValue, // the programmatic property value (current)
  validationSchema, // Allow custom Yup schemas ... set on "propertyValue"
  onClose,
  onSubmit,
}: EditPropertyModalProps) {
  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content medium>
        <Modal.Header
          icon={SvgEdit}
          title={`Edit ${propertyTitle}`}
          onClose={onClose}
        />
        <Modal.Body>
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
                <TextFormField
                  vertical
                  label={propertyDetails || ""}
                  name="propertyValue"
                  placeholder="Property value"
                />

                <Modal.Footer>
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
                </Modal.Footer>
              </Form>
            )}
          </Formik>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
