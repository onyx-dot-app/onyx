import { Image } from "expo-image";
import { useState } from "react";

import { faviconUrl } from "@/chat/citations";
import { SearchDoc } from "@/chat/contracts/documents";
import { ConnectorSourceIcon } from "@/components/chat/ConnectorSourceIcon";
import { Icon } from "@/components/ui/icon";
import SvgFileText from "@/icons/file-text";

interface SourceIconProps {
  doc: SearchDoc;
  size?: number;
}

export function SourceIcon({ doc, size = 18 }: SourceIconProps) {
  const [failed, setFailed] = useState(false);

  if (!doc.is_internet) {
    return <ConnectorSourceIcon source={doc.source_type} size={size} />;
  }

  const uri = faviconUrl(doc.link);
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
