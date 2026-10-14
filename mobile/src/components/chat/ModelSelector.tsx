/*
 * The composer's model picker. Web puts its MultiModelSelector above the input bar; this sits
 * beside the send button instead, because the mobile composer sticks to the keyboard and the
 * space above it belongs to the conversation.
 *
 * Single-select only — web's parallel multi-model comparison has no mobile counterpart yet.
 */
import { ScrollView, View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { LineItemButton } from "@/components/ui/line-item-button";
import { Popover } from "@/components/ui/popover";
import { Text } from "@/components/ui/text";
import {
  groupModelOptions,
  isSameModelOption,
  type ModelOption,
} from "@/chat/models";
import { useComposerTools } from "@/state/ComposerToolsProvider";
import SvgCpu from "@/icons/cpu";

// Yoga never shrinks the pill on its own, so without a cap a long model name pushes the send
// button off the edge of the composer card.
const TRIGGER_MAX_WIDTH = 140;

const LIST_MAX_HEIGHT = 320;

interface ModelListProps {
  options: ModelOption[];
  selected: ModelOption | null;
  onSelect: (option: ModelOption) => void;
}

/*
 * Kept separate from the popover so it can be rendered, and tested, on its own. The panel itself
 * only mounts after the primitive has measured the trigger, which needs real native layout.
 */
export function ModelList({ options, selected, onSelect }: ModelListProps) {
  const groups = groupModelOptions(options);
  const showGroupHeadings = groups.length > 1;

  return (
    <ScrollView
      style={{ maxHeight: LIST_MAX_HEIGHT }}
      keyboardShouldPersistTaps="handled"
    >
      {groups.map((group) => (
        <View key={group.providerDisplayName}>
          {/* The px-8 matches LineItemButton's own inset, so the heading lines up with the row
              labels below it. */}
          {showGroupHeadings ? (
            <Text
              font="secondary-body"
              color="text-02"
              className="px-8 pb-4 pt-8"
            >
              {group.providerDisplayName}
            </Text>
          ) : null}

          {group.options.map((option) => {
            const isSelected =
              selected != null && isSameModelOption(option, selected);
            return (
              <Popover.Close
                key={`${option.modelProvider}:${option.modelVersion}`}
              >
                <LineItemButton
                  title={option.displayName}
                  titleMaxLines={1}
                  sizePreset="main-ui"
                  variant="section"
                  className={isSelected ? "bg-action-selection-02" : undefined}
                  onPress={() => onSelect(option)}
                />
              </Popover.Close>
            );
          })}
        </View>
      ))}
    </ScrollView>
  );
}

export function ModelSelector() {
  const { modelOptions, effectiveModel, selectModel } = useComposerTools();

  // A lone model is not a choice, so the control would only take up composer width.
  if (modelOptions.length < 2) return null;

  return (
    <Popover>
      {/* These classes reproduce SelectButton's resting look, which this cannot simply be. */}
      <Popover.Trigger
        className="h-28 flex-row items-center justify-center rounded-08 px-8"
        accessibilityLabel={
          effectiveModel
            ? `Model: ${effectiveModel.displayName}`
            : "Select model"
        }
      >
        <View className="p-2">
          <Icon as={SvgCpu} size={16} className="text-text-03" />
        </View>
        <Text
          font="main-ui-body"
          color="text-04"
          numberOfLines={1}
          ellipsizeMode="tail"
          className="mx-4 shrink"
          style={{ maxWidth: TRIGGER_MAX_WIDTH }}
        >
          {effectiveModel?.displayName ?? "Model"}
        </Text>
      </Popover.Trigger>

      {/* Bounded rather than fixed: model names run from "GPT-5" to "Claude Sonnet 4.5 (Bedrock)",
          so any single width is either half empty or clipping. */}
      <Popover.Content
        side="top"
        align="end"
        className="min-w-[180px] max-w-[300px]"
      >
        <ModelList
          options={modelOptions}
          selected={effectiveModel}
          onSelect={selectModel}
        />
      </Popover.Content>
    </Popover>
  );
}
