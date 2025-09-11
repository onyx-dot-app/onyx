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
          model_name: Yup.string().required(i18n.t(k.MODEL_NAME_REQUIRED)),
          model_dim: Yup.number().required(i18n.t(k.MODEL_DIMENSION_REQUIRED)),
          normalize: Yup.boolean().required(),
          query_prefix: Yup.string(),
          pass_prefix: Yup.string(),
          provider_type: Yup.string().required(
            i18n.t(k.PROVIDER_TYPE_REQUIRED)
          ),
          api_key: Yup.string().optional(),
          enabled: Yup.boolean(),
          api_url: Yup.string().required(i18n.t(k.API_BASE_URL_REQUIRED)),
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
              label={i18n.t(k.MODEL_NAME_LABEL)}
              subtext={`${i18n.t(k.THE_NAME_OF_THE)} ${
                embeddingType === EmbeddingProvider.AZURE
                  ? i18n.t(k.AZURE)
                  : i18n.t(k.LITELLM)
              } ${i18n.t(k.MODEL1)}`}
              placeholder={i18n.t(k.EXAMPLE_PLACEHOLDER)}
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="model_dim"
              label={i18n.t(k.MODEL_DIMENSION_LABEL)}
              subtext={i18n.t(k.MODEL_DIMENSION_SUBTEXT)}
              placeholder={i18n.t(k.EXAMPLE_1536)}
              type="number"
              autoCompleteDisabled={true}
            />

            <BooleanFormField
              removeIndent
              name="normalize"
              label={i18n.t(k.NORMALIZATION)}
              subtext={i18n.t(k.NORMALIZE_EMBEDDINGS)}
            />

            <TextFormField
              name="query_prefix"
              label={i18n.t(k.QUERY_PREFIX_LABEL)}
              subtext={i18n.t(k.QUERY_PREFIX_SUBTEXT)}
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="passage_prefix"
              label={i18n.t(k.PASSAGE_PREFIX_LABEL)}
              subtext={i18n.t(k.PASSAGE_PREFIX_SUBTEXT)}
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
