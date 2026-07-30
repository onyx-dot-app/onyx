// The cited-sources surface: a "Sources · N" button under a completed answer, and the bottom-sheet
// list it opens (mirrors web's mobile DocumentsSidebar Modal). Sections: Cited / More / User Files.
import { Modal, Pressable, ScrollView, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { SelectedSources } from "@/chat/citations";
import { SearchDoc } from "@/chat/contracts/documents";
import { openSource } from "@/chat/openSource";
import { SourceIcon } from "@/components/chat/SourceIcon";
import { SourceRow } from "@/components/chat/SourceRow";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Text } from "@/components/ui/text";
import SvgX from "@/icons/x";

interface CitedSourcesBarProps {
  iconDocs: SearchDoc[];
  count: number;
  onPress: () => void;
}

export function CitedSourcesBar({
  iconDocs,
  count,
  onPress,
}: CitedSourcesBarProps) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={`Sources, ${count}`}
      className="flex-row items-center gap-8 self-start rounded-12 border border-border-01 bg-background-tint-00 px-8 py-6 active:bg-background-tint-01"
    >
      {iconDocs.length > 0 ? (
        <View className="flex-row">
          {iconDocs.map((doc, index) => (
            <View
              key={doc.document_id}
              style={index > 0 ? { marginLeft: -6 } : undefined}
            >
              <SourceIcon doc={doc} size={16} />
            </View>
          ))}
        </View>
      ) : null}
      <Text font="main-ui-action" color="text-03">
        Sources · {count}
      </Text>
    </Pressable>
  );
}

interface CitedSourcesSheetProps {
  visible: boolean;
  onClose: () => void;
  sources: SelectedSources;
}

export function CitedSourcesSheet({
  visible,
  onClose,
  sources,
}: CitedSourcesSheetProps) {
  const insets = useSafeAreaInsets();
  const { cited, more, files } = sources;

  const sections = [
    { title: "Cited Sources", docs: cited },
    { title: cited.length ? "More" : "Found Sources", docs: more },
    { title: "User Files", docs: files },
  ].filter((section) => section.docs.length > 0);

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      {/* Semantic color tokens can't express translucency (bare CSS vars, no alpha channel), so the
          dimming scrim uses a raw rgba — the one place a non-token color is warranted. */}
      <Pressable
        className="flex-1 justify-end"
        style={{ backgroundColor: "rgba(0, 0, 0, 0.4)" }}
        onPress={onClose}
      >
        {/* Stop taps inside the sheet from dismissing it. */}
        <Pressable
          onPress={() => {}}
          className="rounded-t-20 border-t border-border-01 bg-background-tint-00 px-16 pt-16"
          style={{ paddingBottom: insets.bottom + 16 }}
        >
          <View className="mb-8 flex-row items-center justify-between">
            <Text font="main-content-emphasis" color="text-04">
              Sources
            </Text>
            <Button
              icon={SvgX}
              prominence="tertiary"
              size="sm"
              accessibilityLabel="Close"
              onPress={onClose}
            />
          </View>

          <ScrollView
            className="max-h-[420px]"
            keyboardShouldPersistTaps="handled"
            contentContainerClassName="gap-12 pb-8"
          >
            {sections.map((section, index) => (
              <View key={section.title} className="gap-8">
                {index > 0 ? <Separator /> : null}
                <Text font="secondary-body" color="text-02">
                  {section.title}
                </Text>
                {section.docs.map((doc) => (
                  <SourceRow
                    key={doc.document_id}
                    doc={doc}
                    onPress={() => openSource(doc)}
                  />
                ))}
              </View>
            ))}
          </ScrollView>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
