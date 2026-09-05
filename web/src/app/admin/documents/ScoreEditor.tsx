import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";
import { updateBoost } from "./lib";
import { EditableValue } from "@/components/EditableValue";

export const ScoreSection = ({
  documentId,
  initialScore,
  refresh,
  consistentWidth = true,
}: {
  documentId: string;
  initialScore: number;
  refresh: () => void;
  consistentWidth?: boolean;
}) => {
  const t = useTranslations("admin.documents");

  const onSubmit = async (value: string) => {
    const numericScore = Number(value);
    if (isNaN(numericScore)) {
      toast.error(t("score.notANumber.toast"));
      return false;
    }

    const errorMsg = await updateBoost(documentId, numericScore);
    if (errorMsg) {
      toast.error(errorMsg);
      return false;
    } else {
      toast.success(t("score.updated.toast"));
      refresh();
    }

    return true;
  };

  return (
    <EditableValue
      initialValue={initialScore.toString()}
      onSubmit={onSubmit}
      consistentWidth={consistentWidth}
    />
  );
};
