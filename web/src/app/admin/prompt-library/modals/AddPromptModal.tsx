import React from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { Button } from "@/components/ui/button";

import { BookstackIcon } from "@/components/icons/icons";
import { AddPromptModalProps } from "../interfaces";
import { TextFormField } from "@/components/admin/connectors/Field";
import { Modal } from "@/components/Modal";

const AddPromptSchema = Yup.object().shape({
  title: Yup.string().required("Title is required"),
  prompt: Yup.string().required("Prompt is required"),
});

const AddPromptModal = ({ onClose, onSubmit }: AddPromptModalProps) => {
  return (
    <Modal onOutsideClick={onClose} width="w-full max-w-3xl">
      <Formik
        initialValues={{
          title: "",
          prompt: "",
        }}
        validationSchema={AddPromptSchema}
        onSubmit={(values, { setSubmitting }) => {
          onSubmit({
            prompt: values.title,
            content: values.prompt,
          });
          setSubmitting(false);
          onClose();
        }}
      >
        {({ isSubmitting, setFieldValue }) => (
          <Form>
            <h2 className="w-full text-2xl gap-x-2 text-emphasis font-bold mb-3 flex items-center">
              <BookstackIcon size={20} />
              Add prompt
            </h2>

            <TextFormField
              label="Title"
              name="title"
              placeholder="Title (e.g. 'Reword')"
            />

            <TextFormField
              isTextArea
              label="Prompt"
              name="prompt"
              placeholder="Enter a prompt (e.g. 'help me rewrite the following politely and concisely for professional communication')"
            />

            <Button
              type="submit"
              className="w-full"
              disabled={isSubmitting}
              variant="submit"
            >
              Add prompt
            </Button>
          </Form>
        )}
      </Formik>
    </Modal>
  );
};

export default AddPromptModal;
