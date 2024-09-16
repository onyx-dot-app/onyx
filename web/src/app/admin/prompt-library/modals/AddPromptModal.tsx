import React from "react";
import { Formik, Form, Field, ErrorMessage } from "formik";
import * as Yup from "yup";
import { ModalWrapper } from "@/components/modals/ModalWrapper";
import { Button, Textarea, TextInput } from "@tremor/react";

import { BookstackIcon } from "@/components/icons/icons";
import { AddPromptModalProps } from "../interfaces";
import { TextFormField } from "@/components/admin/connectors/Field";

const AddPromptSchema = Yup.object().shape({
  title: Yup.string().required("Title is required"),
  prompt: Yup.string().required("Prompt is required"),
});

const AddPromptModal = ({ onClose, onSubmit }: AddPromptModalProps) => {
  return (
    <ModalWrapper onClose={onClose} modalClassName="max-w-xl">
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

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              Add prompt
            </Button>
          </Form>
        )}
      </Formik>
    </ModalWrapper>
  );
};

export default AddPromptModal;
