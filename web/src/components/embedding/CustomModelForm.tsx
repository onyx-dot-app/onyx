import i18n from "@/i18n/init";
import k from "./../../i18n/keys";
import {
  BooleanFormField,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { Button } from "@/components/ui/button";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { HostedEmbeddingModel } from "./interfaces";

export function CustomModelForm({
  onSubmit,
}: {
  onSubmit: (model: HostedEmbeddingModel) => void;
}) {
  return (
    <div>
      <Formik
        initialValues={{
          model_name: "",
          model_dim: "",
          query_prefix: "",
          passage_prefix: "",
          description: "",
          normalize: true,
        }}
        validationSchema={Yup.object().shape({
          model_name: Yup.string().required(
            "Пожалуйста, введите имя модели встраивания"
          ),
          model_dim: Yup.number().required(
            "Пожалуйста, введите размерность встраиваний, сгенерированных моделью"
          ),
          query_prefix: Yup.string(),
          passage_prefix: Yup.string(),
          normalize: Yup.boolean().required(),
        })}
        onSubmit={async (values, formikHelpers) => {
          onSubmit({
            ...values,
            model_dim: parseInt(values.model_dim),
            api_key: null,
            provider_type: null,
            index_name: null,
            api_url: null,
          });
        }}
      >
        {({ isSubmitting }) => (
          <Form>
            <TextFormField
              name="model_name"
              label="Название:"
              subtext="Имя модели на Hugging Face"
              placeholder="Например, 'nomic-ai/nomic-embed-text-v1'"
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="model_dim"
              label="Размерность модели:"
              subtext="Размерность вложений, сгенерированных моделью"
              placeholder="Например, '768'"
              autoCompleteDisabled={true}
              type="number"
            />

            <TextFormField
              min={-1}
              name="description"
              label="Описание:"
              subtext="Описание вашей модели"
              placeholder=""
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="query_prefix"
              label="[Необязательно] Префикс запроса:"
              subtext={
                <>
                  {i18n.t(k.THE_PREFIX_SPECIFIED_BY_THE_MO)}
                  <i>{i18n.t(k.QUERIES)}</i>{" "}
                  {i18n.t(k.BEFORE_PASSING_THEM_TO_THE_MOD)}
                </>
              }
              placeholder="Например, 'query: '"
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="passage_prefix"
              label="[Необязательно] Префикс прохода:"
              subtext={
                <>
                  {i18n.t(k.THE_PREFIX_SPECIFIED_BY_THE_MO)}
                  <i>{i18n.t(k.PASSAGES)}</i>{" "}
                  {i18n.t(k.BEFORE_PASSING_THEM_TO_THE_MOD)}
                </>
              }
              placeholder="Например, 'passage: '"
              autoCompleteDisabled={true}
            />

            <BooleanFormField
              removeIndent
              name="normalize"
              label="Normalize Embeddings"
              subtext="Нормализовать или нет вложения, сгенерированные моделью. Если есть сомнения, оставьте этот флажок."
            />

            <Button
              type="submit"
              disabled={isSubmitting}
              className="w-64 mx-auto"
            >
              {i18n.t(k.CHOOSE)}
            </Button>
          </Form>
        )}
      </Formik>
    </div>
  );
}
