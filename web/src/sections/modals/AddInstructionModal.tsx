"use client";

import { Formik, Form } from "formik";
import * as Yup from "yup";
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
  const modal = useModal();
  const { currentProjectDetails, upsertInstructions } = useProjectsContext();

  return (
    <Modal open={modal.isOpen} onOpenChange={modal.toggle}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgAddLines}
          title="设置项目指令"
          description="指定此项目中聊天会话的行为或语气。"
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
              console.error("保存指令失败", e);
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
                  placeholder="我的目标是... 请在回答中注意..."
                />
              </Modal.Body>
              <Modal.Footer>
                <Button
                  prominence="secondary"
                  type="button"
                  onClick={() => modal.toggle(false)}
                >
                  取消
                </Button>
                <Button
                  type="submit"
                  disabled={isSubmitting || !dirty || !isValid}
                >
                  保存指令
                </Button>
              </Modal.Footer>
            </Form>
          )}
        </Formik>
      </Modal.Content>
    </Modal>
  );
}
