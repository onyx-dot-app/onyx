"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { useProjectsContext } from "@/lib/projects/providers";
import { InputVertical, toast } from "@opal/layouts";
import { useAppPosition } from "@/lib/position/hooks";
import { useModal } from "@opal/components";
import { SvgFolderPlus } from "@opal/icons";
import { Modal } from "@opal/components";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

interface CreateProjectModalProps {
  initialProjectName?: string;
}

export default function CreateProjectModal({
  initialProjectName,
}: CreateProjectModalProps) {
  const t = useTranslations("chat");
  const { createProject } = useProjectsContext();
  const appPosition = useAppPosition();
  const modal = useModal();
  const validationSchema = useMemo(
    () =>
      Yup.object({
        projectName: Yup.string()
          .trim()
          .required(t("projects.createModal.nameRequired.error")),
      }),
    [t]
  );

  return (
    <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgFolderPlus}
          title={t("projects.createModal.title")}
          description={t("projects.createModal.description")}
          onClose={() => modal.toggle(false)}
        />
        <Formik
          initialValues={{ projectName: initialProjectName ?? "" }}
          validationSchema={validationSchema}
          validateOnMount
          enableReinitialize
          onSubmit={async (values, { setSubmitting }) => {
            const name = values.projectName.trim();
            try {
              const newProject = await createProject(name);
              appPosition.openProject(newProject.id);
              modal.toggle(false);
            } catch {
              toast.error(
                t("projects.createModal.createError.toast", { name })
              );
            } finally {
              setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, isValid }) => (
            <Form>
              <Modal.Body>
                <InputVertical
                  title={t("projects.createModal.name.label")}
                  withLabel="projectName"
                >
                  <InputTypeInField
                    name="projectName"
                    placeholder={t("projects.createModal.name.placeholder")}
                    clearButton
                  />
                </InputVertical>
              </Modal.Body>
              <Modal.Footer>
                <Button
                  prominence="secondary"
                  type="button"
                  onClick={() => modal.toggle(false)}
                >
                  {t("projects.createModal.cancelButton.label")}
                </Button>
                <Button type="submit" disabled={isSubmitting || !isValid}>
                  {t("projects.createModal.submitButton.label")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
