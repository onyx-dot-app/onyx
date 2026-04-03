import { SvgTrash } from "@opal/icons";
import { Button } from "@opal/components";

export interface DeleteButtonProps {
  onClick?: (event: React.MouseEvent<HTMLElement>) => void | Promise<void>;
  disabled?: boolean;
}

export function DeleteButton({ onClick, disabled }: DeleteButtonProps) {
  return (
    <Button
      disabled={disabled}
      onClick={onClick}
      icon={SvgTrash}
      tooltip="Delete"
      prominence="tertiary"
      size="sm"
    />
  );
}
