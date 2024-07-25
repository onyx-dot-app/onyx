import { Feedback } from "@/lib/types";
import { Badge } from "@tremor/react";

export function FeedbackBadge({
  feedback,
}: {
  feedback?: Feedback | "mixed" | null;
}) {
  let feedbackBadge;
  switch (feedback) {
    case "like":
      feedbackBadge = (
        <Badge color="green" className="text-sm">
          Like
        </Badge>
      );
      break;
    case "dislike":
      feedbackBadge = (
        <Badge color="red" className="text-sm">
          Dislike
        </Badge>
      );
      break;
    case "mixed":
      feedbackBadge = (
        <Badge color="purple" className="text-sm">
          Mixed
        </Badge>
      );
      break;
    default:
      feedbackBadge = (
        <Badge color="gray" className="text-sm">
          N/A
        </Badge>
      );
      break;
  }
  return feedbackBadge;
}
