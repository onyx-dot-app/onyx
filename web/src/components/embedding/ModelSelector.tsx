import { getCurrentModelCopy } from "@/app/admin/embeddings/interfaces";
import {
  EmbeddingModelDescriptor,
  getIconForRerankType,
  getTitleForRerankType,
  HostedEmbeddingModel,
} from "./interfaces";
import { FiExternalLink } from "react-icons/fi";
import CardSection from "../admin/CardSection";

export function ModelPreview({
  model,
  display,
}: {
  model: EmbeddingModelDescriptor;
  display?: boolean;
}) {
  const currentModelCopy = getCurrentModelCopy(model.model_name);

  return (
    <CardSection
      className={`shadow-md ${
        display ? "bg-inverted rounded-lg p-4" : "bg-accent-background p-2"
      } w-96 flex flex-col`}
    >
      <div className="font-bold text-lg flex">{model.model_name}</div>
      <div className="text-sm mt-1 mx-1">
        {model.description ||
          currentModelCopy?.description ||
          "Custom model—no description is available."}
      </div>
    </CardSection>
  );
}

export function ModelOption({
  model,
  onSelect,
  selected,
}: {
  model: HostedEmbeddingModel;
  onSelect?: (model: HostedEmbeddingModel) => void;
  selected: boolean;
}) {
  const currentModelCopy = getCurrentModelCopy(model.model_name);

  return (
    <div
      className={`p-4 w-96 border rounded-lg transition-all duration-200 ${
        selected
          ? "border-blue-800 bg-blue-50 dark:bg-blue-950 dark:border-blue-700 shadow-md"
          : "border-background-200 hover:border-blue-300 hover:shadow-sm"
      }`}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold text-lg">{model.model_name}</h3>

        {model.link && (
          <a
            href={model.link}
            target="_blank"
            rel="noopener noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-blue-500 hover:text-blue-700 transition-colors duration-200"
          >
            <FiExternalLink size={18} />
          </a>
        )}
      </div>
      <p className="text-sm k text-text-600 dark:text-neutral-400 text-left mb-2">
        {model.description ||
          currentModelCopy?.description ||
          "Custom model—no description is available."}
      </p>
      <div className="text-xs text-text-500">
        {model.isDefault ? "Default" : "Self-hosted"}
      </div>
      {onSelect && (
        <div className="mt-3">
          <button
            className={`w-full p-2 rounded-lg text-sm ${
              selected
                ? "bg-background-125 border border-border cursor-not-allowed"
                : "bg-background border border-border hover:bg-accent-background-hovered cursor-pointer"
            }`}
            onClick={(e) => {
              e.stopPropagation();
              if (!selected) onSelect(model);
            }}
            disabled={selected}
          >
            {selected ? "Selected Model" : "Select Model"}
          </button>
        </div>
      )}
    </div>
  );
}
export function ModelSelector({
  modelOptions,
  setSelectedModel,
  currentEmbeddingModel,
}: {
  currentEmbeddingModel: HostedEmbeddingModel;
  modelOptions: HostedEmbeddingModel[];
  setSelectedModel: (model: HostedEmbeddingModel) => void;
}) {
  const groupedModelOptions = modelOptions.reduce(
    (acc, model) => {
      const [type] = model.model_name.split("/");
      if (!acc[type]) {
        acc[type] = [];
      }
      acc[type].push(model);
      return acc;
    },
    {} as Record<string, HostedEmbeddingModel[]>
  );

  return (
    <div>
      <div className="flex flex-col gap-y-6 gap-6">
        {Object.entries(groupedModelOptions).map(([type, models]) => (
          <div key={type}>
            <div className="flex items-center mb-2">
              {getIconForRerankType(type)}
              <h2 className="ml-2 mt-2 text-xl font-bold">
                {getTitleForRerankType(type)}
              </h2>
            </div>

            <div className="flex mt-4 flex-wrap gap-4">
              {models.map((modelOption) => (
                <ModelOption
                  key={modelOption.model_name}
                  model={modelOption}
                  onSelect={setSelectedModel}
                  selected={currentEmbeddingModel === modelOption}
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
