import { getCurrentModelCopy } from "@/app/admin/embeddings/interfaces";
import {
  EmbeddingModelDescriptor,
  getIconForRerankType,
  getTitleForRerankType,
  getFormattedProviderName,
  HostedEmbeddingModel,
  CloudEmbeddingModel,
} from "./interfaces";
import { FiExternalLink } from "react-icons/fi";
import CardSection from "../admin/CardSection";

export function ModelPreview({
  model,
  display,
  showDetails = false,
}: {
  model: EmbeddingModelDescriptor;
  display?: boolean;
  showDetails?: boolean;
}) {
  const currentModelCopy = getCurrentModelCopy(model.model_name);

  return (
    <CardSection
      className={`shadow-lg rounded-16 bg-background-tint-00 ${
        display ? "p-4" : "p-2"
      } w-96 flex flex-col`}
    >
      <div className="font-bold text-lg flex">{model.model_name}</div>

      <div className="text-sm mt-1 mx-1 mb-3">
        {model.description ||
          currentModelCopy?.description ||
          "Custom model—no description is available."}
      </div>

      {showDetails && (
        <div className="pt-4 border-t border-border space-y-3">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="font-semibold text-text-700">Dimensions:</span>
              <div className="text-text-600">
                {model.model_dim.toLocaleString()}
              </div>
            </div>

            <div>
              <span className="font-semibold text-text-700">Provider:</span>
              <div className="text-text-600">
                {getFormattedProviderName(model.provider_type)}
              </div>
            </div>

            <div>
              <span className="font-semibold text-text-700">Normalized:</span>
              <div className="text-text-600">
                {model.normalize ? "Yes" : "No"}
              </div>
            </div>

            {"embedding_precision" in model &&
              (model as any).embedding_precision && (
                <div>
                  <span className="font-semibold text-text-700">
                    Precision:
                  </span>
                  <div className="text-text-600">
                    {(model as any).embedding_precision}
                  </div>
                </div>
              )}

            {"isDefault" in model &&
              (model as HostedEmbeddingModel).isDefault && (
                <div>
                  <span className="font-semibold text-text-700">Type:</span>
                  <div className="text-text-600">Default</div>
                </div>
              )}

            {"pricePerMillion" in model && (
              <div>
                <span className="font-semibold text-text-700">
                  Price/Million:
                </span>
                <div className="text-text-600">
                  ${(model as CloudEmbeddingModel).pricePerMillion}
                </div>
              </div>
            )}
          </div>

          {(model.query_prefix || model.passage_prefix) && (
            <div className="space-y-2">
              {model.query_prefix && (
                <div>
                  <span className="font-semibold text-text-700">
                    Query Prefix:
                  </span>
                  <div className="text-text-600 font-mono text-xs p-2 rounded">
                    &quot;{model.query_prefix}&quot;
                  </div>
                </div>
              )}

              {model.passage_prefix && (
                <div>
                  <span className="font-semibold text-text-700">
                    Passage Prefix:
                  </span>
                  <div className="text-text-600 font-mono text-xs p-2 rounded">
                    &quot;{model.passage_prefix}&quot;
                  </div>
                </div>
              )}
            </div>
          )}

          {model.api_url && (
            <div>
              <span className="font-semibold text-text-700">API URL:</span>
              <div className="text-text-600 font-mono text-xs bg-background p-2 rounded break-all">
                {model.api_url}
              </div>
            </div>
          )}

          {model.api_version && (
            <div>
              <span className="font-semibold text-text-700">API Version:</span>
              <div className="text-text-600">{model.api_version}</div>
            </div>
          )}

          {model.deployment_name && (
            <div>
              <span className="font-semibold text-text-700">Deployment:</span>
              <div className="text-text-600">{model.deployment_name}</div>
            </div>
          )}

          {"link" in model && (model as HostedEmbeddingModel).link && (
            <div className="pt-2">
              <a
                href={(model as HostedEmbeddingModel).link}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center text-blue-500 hover:text-blue-700 transition-colors duration-200 text-sm"
              >
                <span>View Documentation</span>
                <FiExternalLink className="ml-1" size={14} />
              </a>
            </div>
          )}
        </div>
      )}
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
      if (type !== undefined) {
        if (!acc[type]) {
          acc[type] = [];
        }

        const acc_by_type = acc[type];
        if (acc_by_type !== undefined) {
          acc_by_type.push(model);
        }
      }

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
