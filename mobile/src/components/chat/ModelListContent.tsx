import { useMemo, useState, type ComponentType } from "react";
import { Dimensions, Pressable, ScrollView, TextInput, View } from "react-native";

import { Text } from "@/components/opal";
import { SvgCheck } from "@/components/icons/SvgCheck";
import { SvgChevronRight } from "@/components/icons/SvgChevronRight";
import { SvgSearch } from "@/components/icons/SvgSearch";
import { useToken } from "@/theme/ThemeProvider";
import { typography } from "@/theme/generated/typography";
import {
  buildLlmOptions,
  getModelIcon,
  groupLlmOptions,
} from "@/lib/languageModels";
import type {
  LLMOption,
  LLMProviderDescriptor,
  SelectedModel,
} from "@/lib/types";

// Popover content for the model selector — native mirror of web ModelListContent:
// search box, provider groups (flat when single provider), model rows with a
// capabilities sub-label and a selected check (action-link-05), + loading/empty.

const optionKey = (o: {
  name: string;
  provider: string;
  modelName: string;
}) => `${o.name}|${o.provider}|${o.modelName}`;

function capabilities(o: LLMOption): string {
  const caps: string[] = [];
  if (o.supportsReasoning) caps.push("Reasoning");
  if (o.supportsImageInput) caps.push("Vision");
  return caps.join(", ");
}

interface ModelListContentProps {
  providers: LLMProviderDescriptor[];
  isLoading: boolean;
  selected: SelectedModel | null;
  onSelect: (option: LLMOption) => void;
  // Swappable container/input so this renders correctly inside a bottom sheet
  // (BottomSheetScrollView / BottomSheetTextInput) or a plain surface. Typed loosely
  // since gorhom's variants have compatible-but-not-identical prop shapes.
  ScrollComponent?: ComponentType<any>;
  InputComponent?: ComponentType<any>;
}

export function ModelListContent({
  providers,
  isLoading,
  selected,
  onSelect,
  ScrollComponent = ScrollView,
  InputComponent = TextInput,
}: ModelListContentProps) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const searchTextColor = useToken("text-04");
  const mutedColor = useToken("text-03");

  const options = useMemo(() => buildLlmOptions(providers), [providers]);
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter(
      (o) =>
        o.displayName.toLowerCase().includes(q) ||
        o.modelName.toLowerCase().includes(q) ||
        (o.vendor?.toLowerCase().includes(q) ?? false),
    );
  }, [options, query]);
  const groups = useMemo(() => groupLlmOptions(filtered), [filtered]);

  const selectedKey = selected ? optionKey(selected) : null;
  const isSearching = query.trim().length > 0;
  const maxHeight = Math.round(Dimensions.get("window").height * 0.5);

  function toggle(key: string) {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function renderRow(o: LLMOption) {
    const isSel = optionKey(o) === selectedKey;
    const caps = capabilities(o);
    return (
      <Pressable
        key={optionKey(o)}
        onPress={() => onSelect(o)}
        className="flex-row items-center justify-between rounded-[8px] px-3 py-2 active:bg-background-tint-02"
      >
        <View className="flex-1 pr-2">
          <Text font="main-ui-body" color="text-05" numberOfLines={1}>
            {o.displayName}
          </Text>
          {caps ? (
            <Text font="secondary-body" color="text-03" numberOfLines={1}>
              {caps}
            </Text>
          ) : null}
        </View>
        {isSel ? <SvgCheck size={16} color="action-link-05" /> : null}
      </Pressable>
    );
  }

  return (
    <View>
      {/* Search box (web: InputTypeIn internal, leading search icon) */}
      <View className="mb-2 h-9 flex-row items-center gap-2 rounded-[8px] bg-background-tint-02 px-2">
        <SvgSearch size={16} color={mutedColor} />
        <InputComponent
          value={query}
          onChangeText={setQuery}
          placeholder="Search models..."
          placeholderTextColor={mutedColor}
          style={[
            typography["secondary-body"],
            { flex: 1, color: searchTextColor, padding: 0 },
          ]}
        />
      </View>

      {isLoading ? (
        <Text
          font="secondary-body"
          color="text-03"
          style={{ paddingVertical: 8, paddingHorizontal: 4 }}
        >
          Loading models...
        </Text>
      ) : groups.length === 0 ? (
        <Text
          font="secondary-body"
          color="text-03"
          style={{ paddingVertical: 8, paddingHorizontal: 4 }}
        >
          No models found
        </Text>
      ) : (
        <ScrollComponent
          style={{ maxHeight }}
          showsVerticalScrollIndicator={false}
          keyboardShouldPersistTaps="handled"
        >
          {groups.length === 1
            ? groups[0]?.options.map(renderRow)
            : groups.map((g) => {
                const GroupIcon = getModelIcon(
                  g.options[0]?.provider ?? "",
                  g.options[0]?.vendor,
                  g.options[0]?.modelName,
                );
                const open = isSearching || !collapsed.has(g.key);
                return (
                  <View key={g.key}>
                    <Pressable
                      onPress={() => {
                        if (!isSearching) toggle(g.key);
                      }}
                      className="flex-row items-center gap-2 py-1 pl-2 pr-1"
                    >
                      <GroupIcon size={16} color={mutedColor} />
                      <Text
                        font="secondary-body"
                        color="text-02"
                        numberOfLines={1}
                        style={{ flex: 1 }}
                      >
                        {g.displayName}
                      </Text>
                      <View
                        style={{
                          transform: [{ rotate: open ? "90deg" : "0deg" }],
                        }}
                      >
                        <SvgChevronRight size={16} color={mutedColor} />
                      </View>
                    </Pressable>
                    {open ? g.options.map(renderRow) : null}
                  </View>
                );
              })}
        </ScrollComponent>
      )}
    </View>
  );
}
