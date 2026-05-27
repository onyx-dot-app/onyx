"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
import { Button } from "@opal/components";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { InputVertical } from "@opal/layouts";
import { useAppRouter } from "@/hooks/appNavigation";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { SvgFolderPlus } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { toast } from "@/hooks/useToast";

const validationSchema = Yup.object({
  projectName: Yup.string().trim().required("Project name is required"),
});

interface CreateProjectModalProps {
  initialProjectName?: string;
}

export default function CreateProjectModal({
  initialProjectName,
}: CreateProjectModalProps) {
  const { createProject } = useProjectsContext();
  const modal = useModal();
  const route = useAppRouter();

  return (
    <>
      <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
        <Modal.Content width="sm">
          <Modal.Header
            icon={SvgFolderPlus}
            title="Create New Project"
            description="Use projects to organize your files and chats in one place, and add custom instructions for ongoing work."
            onClose={() => modal.toggle(false)}
          />
          <Formik
            initialValues={{ projectName: initialProjectName ?? "" }}
            validationSchema={validationSchema}
            enableReinitialize
            onSubmit={async (values, { setSubmitting }) => {
              const name = values.projectName.trim();
              try {
                const newProject = await createProject(name);
                route({ projectId: newProject.id });
                modal.toggle(false);
              } catch {
                toast.error(`Failed to create the project ${name}`);
              } finally {
                setSubmitting(false);
              }
            }}
          >
            {({ isSubmitting, isValid }) => (
              <Form>
                <Modal.Body>
                  <InputVertical title="Project Name" withLabel="projectName">
                    <InputTypeInField
                      name="projectName"
                      placeholder="What are you working on?"
                      showClearButton
                    />
                  </InputVertical>
                </Modal.Body>
                <Modal.Footer>
                  <Button
                    prominence="secondary"
                    type="button"
                    onClick={() => modal.toggle(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={isSubmitting || !isValid}>
                    Create Project
                  </Button>
                </Modal.Footer>
              </Form>
            )}
          </Formik>
        </Modal.Content>
      </Modal>
    </>
  );
}
