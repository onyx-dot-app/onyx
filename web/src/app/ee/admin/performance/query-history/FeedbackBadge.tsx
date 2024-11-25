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
          Like
        </Badge>
      );
      break;
    case "dislike":
      feedbackBadge = (
        <Badge variant="destructive" className="text-sm">
          Dislike
        </Badge>
      );
      break;
    case "mixed":
      feedbackBadge = (
        <Badge variant="purple" className="text-sm">
          Mixed
        </Badge>
      );
      break;
    default:
      feedbackBadge = (
        <Badge variant="outline" className="text-sm">
          N/A
        </Badge>
      );
      break;
  }
  return feedbackBadge;
}
