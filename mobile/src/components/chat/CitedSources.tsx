// The cited-sources surface: a "Sources · N" button under a completed answer, and the bottom-sheet
// list it opens (mirrors web's mobile DocumentsSidebar). Sections: Cited / More / User Files.
import { Pressable, ScrollView, View } from "react-native";

import { SelectedSources } from "@/chat/citations";
import { SearchDoc } from "@/chat/contracts/documents";
import { openSource } from "@/chat/openSource";
import { SourceIcon } from "@/components/chat/SourceIcon";
import { SourceRow } from "@/components/chat/SourceRow";
import { Separator } from "@/components/ui/separator";
import { Sheet } from "@/components/ui/sheet";
import { Text } from "@/components/ui/text";

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
  const { cited, more, files } = sources;

  const sections = [
    { title: "Cited Sources", docs: cited },
    { title: cited.length ? "More" : "Found Sources", docs: more },
    { title: "User Files", docs: files },
  ].filter((section) => section.docs.length > 0);

  return (
    <Sheet visible={visible} onClose={onClose} title="Sources">
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
    </Sheet>
  );
}
