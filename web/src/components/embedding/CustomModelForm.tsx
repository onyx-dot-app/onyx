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
            i18n.t(k.EMBEDDING_MODEL_NAME_REQUIRED)
          ),
          model_dim: Yup.number().required(
            i18n.t(k.EMBEDDING_DIMENSION_REQUIRED)
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
              label={i18n.t(k.MODEL_NAME_LABEL)}
              subtext={i18n.t(k.MODEL_NAME_SUBTEXT)}
              placeholder={i18n.t(k.MODEL_NAME_PLACEHOLDER)}
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="model_dim"
              label={i18n.t(k.MODEL_DIMENSION_LABEL)}
              subtext={i18n.t(k.MODEL_DIMENSION_SUBTEXT)}
              placeholder={i18n.t(k.MODEL_DIMENSION_PLACEHOLDER)}
              autoCompleteDisabled={true}
              type="number"
            />

            <TextFormField
              min={-1}
              name="description"
              label={i18n.t(k.DESCRIPTION_LABEL)}
              subtext={i18n.t(k.MODEL_DESCRIPTION_SUBTEXT)}
              placeholder=""
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="query_prefix"
              label={i18n.t(k.QUERY_PREFIX_LABEL)}
              subtext={
                <>
                  {i18n.t(k.THE_PREFIX_SPECIFIED_BY_THE_MO)}
                  <i>{i18n.t(k.QUERIES)}</i>{" "}
                  {i18n.t(k.BEFORE_PASSING_THEM_TO_THE_MOD)}
                </>
              }
              placeholder={i18n.t(k.QUERY_PREFIX_PLACEHOLDER)}
              autoCompleteDisabled={true}
            />

            <TextFormField
              name="passage_prefix"
              label={i18n.t(k.PASSAGE_PREFIX_LABEL)}
              subtext={
                <>
                  {i18n.t(k.THE_PREFIX_SPECIFIED_BY_THE_MO)}
                  <i>{i18n.t(k.PASSAGES)}</i>{" "}
                  {i18n.t(k.BEFORE_PASSING_THEM_TO_THE_MOD)}
                </>
              }
              placeholder={i18n.t(k.PASSAGE_PREFIX_PLACEHOLDER)}
              autoCompleteDisabled={true}
            />

            <BooleanFormField
              removeIndent
              name="normalize"
              label="Normalize Embeddings"
              subtext={i18n.t(k.NORMALIZE_EMBEDDINGS_SUBTEXT)}
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
