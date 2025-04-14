"use client";
import i18n from "i18next";
import k from "./../../../../i18n/keys";

import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
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
      <Title className="mt-8">{i18n.t(k.HERE_ARE_SOME_LOCALLY_HOSTED_M)}</Title>
      <Text className="mb-4">{i18n.t(k.THESE_MODELS_CAN_BE_USED_WITHO)}</Text>
      <ModelSelector
        modelOptions={AVAILABLE_MODELS}
        setSelectedModel={onSelectOpenSource}
        currentEmbeddingModel={selectedProvider}
      />

      <Text className="mt-6">
        {i18n.t(k.ALTERNATIVELY_IF_YOU_KNOW_WH)}{" "}
        <a
          target="_blank"
          href="https://www.sbert.net/"
          className="text-link"
          rel="noreferrer"
        >
          {i18n.t(k.SENTENCETRANSFORMERS)}
        </a>
        {i18n.t(k.COMPATIBLE_MODEL_OF_YOUR_CHOI)}{" "}
        <a
          target="_blank"
          href="https://huggingface.co/models?library=sentence-transformers&sort=trending"
          className="text-link"
          rel="noreferrer"
        >
          {i18n.t(k.HERE)}
        </a>
        {i18n.t(k._8)}
        <br />
        <b>{i18n.t(k.NOTE)}</b> {i18n.t(k.NOT_ALL_MODELS_LISTED_WILL_WOR)}
      </Text>
      {!configureModel && (
        <Button
          onClick={() => setConfigureModel(true)}
          className="mt-4"
          variant="secondary"
        >
          {i18n.t(k.CONFIGURE_CUSTOM_MODEL)}
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
