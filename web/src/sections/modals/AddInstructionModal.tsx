"use client";

import { Formik, Form } from "formik";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { Button } from "@opal/components";
import { useProjectsContext } from "@/lib/projects/providers";
import { useModal } from "@opal/components";
import { SvgAddLines } from "@opal/icons";
import { Modal } from "@opal/components";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";

const validationSchema = Yup.object({
  instructions: Yup.string(),
});

export default function AddInstructionModal() {
  const t = useTranslations("skills.modals");
  const modal = useModal();
  const { currentProjectDetails, upsertInstructions } = useProjectsContext();

  return (
    <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgAddLines}
          title={t("addInstruction.header.title")}
          description={t("addInstruction.header.description")}
          onClose={() => modal.toggle(false)}
        />
        <Formik
          initialValues={{
            instructions: currentProjectDetails?.project?.instructions ?? "",
          }}
          validationSchema={validationSchema}
          onSubmit={async (values, { setSubmitting }) => {
            try {
              await upsertInstructions(values.instructions.trim());
              modal.toggle(false);
            } catch (e) {
              console.error("Failed to save instructions", e);
            } finally {
              setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, dirty, isValid }) => (
            <Form>
              <Modal.Body>
                <InputTextAreaField
                  name="instructions"
                  placeholder={t(
                    "addInstruction.instructionsField.placeholder"
                  )}
                />
              </Modal.Body>
              <Modal.Footer>
                <Button
                  prominence="secondary"
                  type="button"
                  onClick={() => modal.toggle(false)}
                >
                  {t("addInstruction.cancelButton.label")}
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting || !dirty || !isValid}
                >
                  {t("addInstruction.saveButton.label")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
