// A source's leading glyph: the site favicon for linked/web docs (public URL — plain expo-image,
// NOT BearerImage), falling back to a generic file glyph. No per-connector logo set yet (9a scope).
import { Image } from "expo-image";
import { useState } from "react";

import { faviconUrl } from "@/chat/citations";
import { SearchDoc } from "@/chat/contracts/documents";
import { Icon } from "@/components/ui/icon";
import SvgFileText from "@/icons/file-text";

interface SourceIconProps {
  doc: SearchDoc;
  size?: number;
}

export function SourceIcon({ doc, size = 18 }: SourceIconProps) {
  const uri = faviconUrl(doc.link);
  const [failed, setFailed] = useState(false);

  if (!uri || failed) {
    return <Icon as={SvgFileText} size={size} className="text-text-03" />;
  }
  return (
    <Image
      source={{ uri }}
      style={{ width: size, height: size, borderRadius: 4 }}
      contentFit="contain"
      onError={() => setFailed(true)}
    />
  );
}
