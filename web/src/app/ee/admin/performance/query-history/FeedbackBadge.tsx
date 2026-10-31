import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { Feedback } from "@/lib/types";

export function FeedbackBadge({
  feedback,
}: {
  feedback?: Feedback | "mixed" | null;
}) {
  const t = useTranslations("admin.queryHistory");
  let feedbackBadge;
  switch (feedback) {
    case "like":
      feedbackBadge = (
        <Badge variant="success" className="text-sm">
          {t("feedback.like.label")}
        </Badge>
      );
      break;
    case "dislike":
      feedbackBadge = (
        <Badge variant="destructive" className="text-sm">
          {t("feedback.dislike.label")}
        </Badge>
      );
      break;
    case "mixed":
      feedbackBadge = (
        <Badge variant="purple" className="text-sm">
          {t("feedback.mixed.label")}
        </Badge>
      );
      break;
    default:
      feedbackBadge = (
        <Badge variant="outline" className="text-sm">
          {t("feedback.na.label")}
        </Badge>
      );
      break;
  }
  return feedbackBadge;
}
