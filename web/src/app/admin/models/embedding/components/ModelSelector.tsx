import { EmbeddingModelDescriptor, HostedEmbeddingModel } from "./types";
import { FiStar } from "react-icons/fi";

export function ModelPreview({ model }: { model: EmbeddingModelDescriptor }) {
  return (
    <div
      className={
        "p-2 border border-border rounded shadow-md bg-hover-light w-96 flex flex-col"
      }
    >
      <div className="font-bold text-lg flex">{model.model_name}</div>
      <div className="text-sm mt-1 mx-1">
        {model.description
          ? model.description
          : "Custom model—no description is available."}
      </div>
    </div>
  );
}

export function ModelOption({
  model,
  onSelect,
}: {
  model: HostedEmbeddingModel;
  onSelect?: (model: HostedEmbeddingModel) => void;
}) {
  return (
    <div
      className={
        "p-2 border border-border rounded shadow-md bg-hover-light w-96 flex flex-col"
      }
    >
      <div className="font-bold text-lg flex">
        {model.isDefault && <FiStar className="my-auto mr-1 text-accent" />}
        {model.model_name}
      </div>
      <div className="text-sm mt-1 mx-1">
        {model.description
          ? model.description
          : "Custom model—no description is available."}
      </div>
      {model.link && (
        <a
          target="_blank"
          href={model.link}
          className="text-xs text-link mx-1 mt-1"
        >
          See More Details
        </a>
      )}
      {onSelect && (
        <div
          className={`
            m-auto 
            flex 
            mt-3
            mb-1 
            w-fit 
            p-2 
            rounded-lg
            bg-background
            border
            border-border
            cursor-pointer
            hover:bg-hover
            text-sm
            mt-auto`}
          onClick={() => onSelect(model)}
        >
          Select Model
        </div>
      )}
    </div>
  );
}

export function ModelSelector({
  modelOptions,
  setSelectedModel,
}: {
  modelOptions: HostedEmbeddingModel[];
  setSelectedModel: (model: HostedEmbeddingModel) => void;
}) {
  return (
    <div>
      <div className="flex flex-wrap gap-4">
        {modelOptions.map((modelOption) => (
          <ModelOption
            key={modelOption.model_name}
            model={modelOption}
            onSelect={setSelectedModel}
          />
        ))}
      </div>
    </div>
  );
}
