import React from "react";
import { LLMModelDescriptor } from "@/app/admin/configuration/llm/interfaces";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { OpenAIIcon } from "@/components/icons/icons";
import { getDisplayNameForModel } from "@/lib/hooks";

interface ModelSelectorProps {
  models: LLMModelDescriptor[];
  selectedModel: LLMModelDescriptor;
  onSelectModel: (model: LLMModelDescriptor) => void;
}

export const ModelSelector: React.FC<ModelSelectorProps> = ({
  models,
  selectedModel,
  onSelectModel,
}) => (
  <Select
    value={selectedModel.modelName}
    onValueChange={(value) =>
      onSelectModel(models.find((m) => m.modelName === value) || models[0])
    }
  >
    <SelectTrigger className="w-full">
      <SelectValue placeholder="Select a model" />
    </SelectTrigger>
    <SelectContent>
      {models.map((model) => (
        <SelectItem
          icon={OpenAIIcon}
          key={model.modelName}
          value={model.modelName}
        >
          {getDisplayNameForModel(model.modelName)}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
);
