"use client";

import Button from "@/refresh-components/buttons/Button";
import { Text } from "@opal/components";
import { markdown } from "@opal/utils";
import Spacer from "@/refresh-components/Spacer";
import Title from "@/components/ui/title";
import { ModelSelector } from "../../../../components/embedding/ModelSelector";
import {
  AVAILABLE_MODELS,
  CloudEmbeddingModel,
  HostedEmbeddingModel,
} from "../../../../components/embedding/interfaces";
import { CustomModelForm } from "../../../../components/embedding/CustomModelForm";
import { useState } from "react";
import CardSection from "@/components/admin/CardSection";
export default function OpenEmbeddingPage({
  onSelectOpenSource,
  selectedProvider,
}: {
  onSelectOpenSource: (model: HostedEmbeddingModel) => void;
  selectedProvider: HostedEmbeddingModel | CloudEmbeddingModel;
}) {
  const [configureModel, setConfigureModel] = useState(false);
  return (
    <div>
      <Title className="mt-8">
        Here are some locally-hosted models to choose from.
      </Title>
      <Text as="p">
        {
          "These models can be used without any API keys, and can leverage a GPU for faster inference."
        }
      </Text>
      <Spacer rem={1} />
      <ModelSelector
        modelOptions={AVAILABLE_MODELS}
        setSelectedModel={onSelectOpenSource}
        currentEmbeddingModel={selectedProvider}
      />

      <Spacer rem={1.5} />
      <Text as="p">
        {markdown(
          "Alternatively, (if you know what you're doing) you can specify a [SentenceTransformers](https://www.sbert.net/)-compatible model of your choice below. The rough list of supported models can be found [here](https://huggingface.co/models?library=sentence-transformers&sort=trending)."
        )}
      </Text>
      <Text as="p">
        {markdown(
          "**NOTE:** not all models listed will work with Onyx, since some have unique interfaces or special requirements. If in doubt, reach out to the Onyx team."
        )}
      </Text>
      {!configureModel && (
        // TODO(@raunakab): migrate to opal Button once className/iconClassName is resolved
        <Button
          onClick={() => setConfigureModel(true)}
          className="mt-4"
          secondary
        >
          Configure custom model
        </Button>
      )}
      {configureModel && (
        <div className="w-full flex">
          <CardSection className="mt-4 2xl:w-4/6 mx-auto">
            <CustomModelForm onSubmit={onSelectOpenSource} />
          </CardSection>
        </div>
      )}
    </div>
  );
}
