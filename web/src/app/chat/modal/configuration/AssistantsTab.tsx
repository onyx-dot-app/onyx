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
import { Persona } from "@/app/admin/assistants/interfaces";
import { LLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import { getFinalLLM } from "@/lib/llm/utils";
import React, { useEffect, useState } from "react";
import { updateUserAssistantList } from "@/lib/assistants/updateAssistantPreferences";
import { DraggableAssistantCard } from "@/components/assistants/AssistantCards";
import { useAssistants } from "@/components/context/AssistantsContext";
import { useUser } from "@/components/user/UserProvider";

export function AssistantsTab({
  selectedAssistant,
  llmProviders,
  onSelect,
}: {
  selectedAssistant: Persona;
  llmProviders: LLMProviderDescriptor[];
  onSelect: (assistant: Persona) => void;
}) {
  const { refreshUser } = useUser();
  const [_, llmName] = getFinalLLM(llmProviders, null, null);
  const { finalAssistants, refreshAssistants } = useAssistants();
  const [assistants, setAssistants] = useState(finalAssistants);

  useEffect(() => {
    setAssistants(finalAssistants);
  }, [finalAssistants]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  async function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;

    if (over && active.id !== over.id) {
      const oldIndex = assistants.findIndex(
        (item) => item.id.toString() === active.id
      );
      const newIndex = assistants.findIndex(
        (item) => item.id.toString() === over.id
      );
      const updatedAssistants = arrayMove(assistants, oldIndex, newIndex);

      setAssistants(updatedAssistants);
      await updateUserAssistantList(updatedAssistants.map((a) => a.id));
      await refreshUser();
      await refreshAssistants();
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
