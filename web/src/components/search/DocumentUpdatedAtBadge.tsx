import i18n from "@/i18n/init-server";
import k from "@/i18n/keys";
import { timeAgo } from "@/lib/time";
import { MetadataBadge } from "../MetadataBadge";

export function DocumentUpdatedAtBadge({
  updatedAt,
  modal,
}: {
  updatedAt: string;
  modal?: boolean;
}) {
  return (
    <MetadataBadge
      flexNone={modal}
      value={(modal ? "" : i18n.t(k.UPDATED)) + timeAgo(updatedAt)}
    />
  );
}
