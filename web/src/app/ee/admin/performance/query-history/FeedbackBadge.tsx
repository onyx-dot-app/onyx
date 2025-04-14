import i18n from "i18next";
import k from "./../../../../../i18n/keys";
import { Badge } from "@/components/ui/badge";
import { Feedback } from "@/lib/types";

export function FeedbackBadge({
  feedback,
}: {
  feedback?: Feedback | "mixed" | null;
}) {
  let feedbackBadge;
  switch (feedback) {
    case "like":
      feedbackBadge = (
        <Badge variant="success" className="text-sm">
          {i18n.t(k.LIKE)}
        </Badge>
      );

      break;
    case "dislike":
      feedbackBadge = (
        <Badge variant="destructive" className="text-sm">
          {i18n.t(k.DISLIKE)}
        </Badge>
      );

      break;
    case "mixed":
      feedbackBadge = (
        <Badge variant="purple" className="text-sm">
          {i18n.t(k.MIXED)}
        </Badge>
      );

      break;
    default:
      feedbackBadge = (
        <Badge variant="outline" className="text-sm">
          {i18n.t(k.N_A)}
        </Badge>
      );

      break;
  }
  return feedbackBadge;
}
