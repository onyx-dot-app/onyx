"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useTranslation } from "react-i18next";
import { Button } from "@opal/components";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgAddLines } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";

const validationSchema = Yup.object({
  instructions: Yup.string(),
});

export default function AddInstructionModal() {
  const { t } = useTranslation();
  const modal = useModal();
  const { currentProjectDetails, upsertInstructions } = useProjectsContext();

  return (
    <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgAddLines}
          title={t("projects.set_instructions_title")}
          description={t("projects.set_instructions_desc")}
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
                  placeholder={t("projects.instructions_placeholder")}
                />
              </Modal.Body>
              <Modal.Footer>
                <Button
                  prominence="secondary"
                  type="button"
                  onClick={() => modal.toggle(false)}
                >
                  {t("general.cancel")}
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting || !dirty || !isValid}
                >
                  {t("projects.save_instructions")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
