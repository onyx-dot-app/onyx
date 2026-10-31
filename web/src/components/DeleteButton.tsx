import { SvgTrash } from "@opal/icons";
import { Button } from "@opal/components";
import { useTranslations } from "next-intl";

export interface DeleteButtonProps {
  onClick?: (event: React.MouseEvent<HTMLElement>) => void | Promise<void>;
  disabled?: boolean;
}

export function DeleteButton({ onClick, disabled }: DeleteButtonProps) {
  const t = useTranslations("common.deleteButton");
  return (
    <Button
      disabled={disabled}
      onClick={onClick}
      icon={SvgTrash}
      tooltip={t("button.tooltip")}
      aria-label={t("button.tooltip")}
      data-testid="delete-button"
      prominence="tertiary"
      size="sm"
    />
  );
}
