"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@opal/components";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { InputVertical } from "@opal/layouts";
import { useAppRouter } from "@/hooks/appNavigation";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgFolderPlus } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { toast } from "@/hooks/useToast";
import i18n from "@/lib/i18n";

function getValidationSchema() {
  return Yup.object({
    projectName: Yup.string()
      .trim()
      .required(i18n.t("projects.project_name_required")),
  });
}

interface CreateProjectModalProps {
  initialProjectName?: string;
}

export default function CreateProjectModal({
  initialProjectName,
}: CreateProjectModalProps) {
  const { t } = useTranslation();
  const { createProject } = useProjectsContext();
  const modal = useModal();
  const route = useAppRouter();
  const validationSchema = useMemo(() => getValidationSchema(), []);

  return (
    <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgFolderPlus}
          title={t("projects.create_new_project")}
          description={t("projects.create_desc")}
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
              route({ projectId: newProject.id });
              modal.toggle(false);
            } catch {
              toast.error(t("projects.create_failed", { name }));
            } finally {
              setSubmitting(false);
            }
          }}
        >
          {({ isSubmitting, isValid }) => (
            <Form>
              <Modal.Body>
                <InputVertical
                  title={t("projects.project_name")}
                  withLabel="projectName"
                >
                  <InputTypeInField
                    name="projectName"
                    placeholder={t("projects.project_name_placeholder")}
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
                  {t("general.cancel")}
                </Button>
                <Button type="submit" disabled={isSubmitting || !isValid}>
                  {t("projects.create_project")}
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
