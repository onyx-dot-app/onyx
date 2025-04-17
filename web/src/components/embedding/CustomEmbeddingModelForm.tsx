import i18n from "@/i18n/init";
import k from "./../../i18n/keys";
import { CloudEmbeddingModel, EmbeddingProvider } from "./interfaces";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { TextFormField, BooleanFormField } from "../admin/connectors/Field";
import { Dispatch, SetStateAction } from "react";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";
import { EmbeddingDetails } from "@/app/admin/embeddings/EmbeddingModelSelectionForm";

export function CustomEmbeddingModelForm({
  setShowTentativeModel,
  currentValues,
  provider,
  embeddingType,
}: {
  setShowTentativeModel: Dispatch<SetStateAction<CloudEmbeddingModel | null>>;
  currentValues: CloudEmbeddingModel | null;
  provider: EmbeddingDetails;
  embeddingType: EmbeddingProvider;
}) {
  return (
    <div>
      <Formik
        initialValues={
          currentValues || {
            model_name: "",
            model_dim: 768,
            normalize: false,
            query_prefix: "",
            passage_prefix: "",
            provider_type: embeddingType,
            api_key: "",
            enabled: true,
            api_url: provider.api_url,
            description: "",
            index_name: "",
          }
        }
        validationSchema={Yup.object().shape({
          model_name: Yup.string().required("Название модели обязательно"),
          model_dim: Yup.number().required("Требуется размерность модели"),
          normalize: Yup.boolean().required(),
          query_prefix: Yup.string(),
          pass_prefix: Yup.string(),
          provider_type: Yup.string().required("Требуется тип поставщика"),
          api_key: Yup.string().optional(),
          enabled: Yup.boolean(),
          api_url: Yup.string().required("Требуется базовый URL API"),
          description: Yup.string(),
          index_name: Yup.string().nullable(),
        })}
        onSubmit={async (values) => {
          setShowTentativeModel(values as CloudEmbeddingModel);
        }}
      >
        {({ isSubmitting, submitForm, errors }) => (
          <Form>
            <Text className="text-xl text-text-900 font-bold mb-4">
              {i18n.t(k.SPECIFY_DETAILS_FOR_YOUR)}{" "}
              {embeddingType === EmbeddingProvider.AZURE
                ? i18n.t(k.AZURE)
                : i18n.t(k.LITELLM)}{" "}
              {i18n.t(k.PROVIDER_S_MODEL)}
            </Text>
            <TextFormField
              name="model_name"
              label="Название модели:"
              subtext={`${i18n.t(k.THE_NAME_OF_THE)} ${
                embeddingType === EmbeddingProvider.AZURE
                  ? i18n.t(k.AZURE)
                  : i18n.t(k.LITELLM)
              } ${i18n.t(k.MODEL1)}`}
              placeholder="например, 'all-MiniLM-L6-v2'"
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="model_dim"
              label="Размерность модели:"
              subtext="Размерность вложений модели"
              placeholder="например, '1536'"
              type="number"
              autoCompleteDisabled={true}
            />

            <BooleanFormField
              removeIndent
              name="normalize"
              label="Нормализация"
              subtext="Нормализация вложений"
            />

            <TextFormField
              name="query_prefix"
              label="Префикс запроса:"
              subtext="Префикс для вложений запроса"
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="passage_prefix"
              label="Префикс прохода:"
              subtext="Префикс для вложений прохода"
              autoCompleteDisabled={true}
            />

            <Button
              type="submit"
              disabled={isSubmitting}
              className="w-64 mx-auto"
            >
              {i18n.t(k.CONFIGURE)}{" "}
              {embeddingType === EmbeddingProvider.AZURE
                ? i18n.t(k.AZURE)
                : i18n.t(k.LITELLM)}{" "}
              {i18n.t(k.MODEL2)}
            </Button>
          </Form>
        )}
      </Formik>
    </div>
  );
}
