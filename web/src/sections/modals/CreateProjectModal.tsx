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
  projectName: Yup.string().trim().required("项目名称为必填项"),
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
            title="新建项目"
            description="使用项目集中整理文件和聊天，并为持续工作添加自定义指令。"
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
                toast.error(`创建项目“${name}”失败`);
              } finally {
                setSubmitting(false);
              }
            }}
          >
            {({ isSubmitting, isValid }) => (
              <Form>
                <Modal.Body>
                  <InputVertical title="项目名称" withLabel="projectName">
                    <InputTypeInField
                      name="projectName"
                      placeholder="你正在做什么？"
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
                    取消
                  </Button>
                  <Button type="submit" disabled={isSubmitting || !isValid}>
                    创建项目
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
