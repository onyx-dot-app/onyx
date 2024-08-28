import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { Persona } from "@/app/admin/assistants/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { getFinalLLM } from "@/lib/llm/utils";
import React, { useState } from "react";
import { updateUserAssistantList } from "@/lib/assistants/updateAssistantPreferences";
import { DraggableAssistantCard } from "@/components/assistants/AssistantCards";

export function AssistantsTab({
  selectedAssistant,
  availableAssistants,
  llmProviders,
  onSelect,
}: {
  selectedAssistant: Persona;
  availableAssistants: Persona[];
  llmProviders: LLMProviderDescriptor[];
  onSelect: (assistant: Persona) => void;
}) {
  const [_, llmName] = getFinalLLM(llmProviders, null, null);
  const [assistants, setAssistants] = useState(availableAssistants);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      setAssistants((items) => {
        const oldIndex = items.findIndex(
          (item) => item.id.toString() === active.id
        );
        const newIndex = items.findIndex(
          (item) => item.id.toString() === over.id
        );
        const updatedAssistants = arrayMove(items, oldIndex, newIndex);

        updateUserAssistantList(updatedAssistants.map((a) => a.id));

        return updatedAssistants;
      });
    }
  }

  return (
    <div className="py-4">
      <h3 className="px-4 text-lg font-semibold">Change Assistant</h3>
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={assistants.map((a) => a.id.toString())}
          strategy={verticalListSortingStrategy}
        >
          <div className="px-4 pb-2  max-h-[500px] include-scrollbar overflow-y-scroll my-3 grid grid-cols-1 gap-4">
            {assistants.map((assistant) => (
              <DraggableAssistantCard
                key={assistant.id.toString()}
                assistant={assistant}
                isSelected={selectedAssistant.id === assistant.id}
                onSelect={onSelect}
                llmName={llmName}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}
