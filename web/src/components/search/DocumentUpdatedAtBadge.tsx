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
      value={(modal ? "" : "Updated ") + timeAgo(updatedAt)}
    />
  );
}
