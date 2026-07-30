// A tappable source that opens its document (browser for linked docs). Reused by 9b's search/fetch renderers.
import { View } from "react-native";

import { domainOf } from "@/chat/citations";
import { SearchDoc } from "@/chat/contracts/documents";
import { SourceIcon } from "@/components/chat/SourceIcon";
import { Card } from "@/components/ui/card";
import { Text } from "@/components/ui/text";
import { timeAgo } from "@/lib/time";

interface SourceRowProps {
  doc: SearchDoc;
  onPress: () => void;
}

function metaLine(doc: SearchDoc): string {
  const label = domainOf(doc.link) ?? doc.source_type;
  const when = doc.updated_at ? timeAgo(doc.updated_at) : null;
  return when ? `${label} · ${when}` : label;
}

function snippet(doc: SearchDoc): string {
  const raw = doc.match_highlights?.[0] ?? doc.blurb ?? "";
  // Strip Vespa <hi>…</hi> highlight markup so it doesn't render literally.
  const clean = raw.replace(/<\/?hi>/g, "").trim();
  return clean.length > 200 ? `${clean.slice(0, 200)}…` : clean;
}

export function SourceRow({ doc, onPress }: SourceRowProps) {
  const text = snippet(doc);
  return (
    <Card variant="secondary" onPress={onPress} className="gap-6 p-12">
      <View className="flex-row items-center gap-8">
        <SourceIcon doc={doc} size={18} />
        <Text
          font="main-ui-action"
          color="text-05"
          maxLines={1}
          className="flex-1"
        >
          {doc.semantic_identifier || doc.document_id}
        </Text>
      </View>
      <Text font="secondary-body" color="text-02" maxLines={1}>
        {metaLine(doc)}
      </Text>
      {text.length > 0 ? (
        <Text font="secondary-body" color="text-03" maxLines={2}>
          {text}
        </Text>
      ) : null}
    </Card>
  );
}
