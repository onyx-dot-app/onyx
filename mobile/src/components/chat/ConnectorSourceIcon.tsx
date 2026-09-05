// Not SourceIcon: that one glyphs a cited *document* by favicon, this is a connector's brand mark.
import { getSourceMeta, type DocumentSource } from "@/chat/sources";
import { Icon } from "@/components/ui/icon";
import SvgGlobe from "@/icons/globe";

interface ConnectorSourceIconProps {
  source: DocumentSource;
  size?: number;
}

export function ConnectorSourceIcon({
  source,
  size = 16,
}: ConnectorSourceIconProps) {
  const meta = getSourceMeta(source);
  // Only the fallback glyph takes the row's ink; logos carry their own colours.
  if (!meta) {
    return <Icon as={SvgGlobe} size={size} className="text-text-03" />;
  }
  return <Icon as={meta.icon} size={size} />;
}
