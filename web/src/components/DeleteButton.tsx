import { SvgTrash } from "@opal/icons";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";

export interface DeleteButtonProps {
  onClick?: (event: React.MouseEvent<HTMLElement>) => void | Promise<void>;
  disabled?: boolean;
}

export function DeleteButton({ onClick, disabled }: DeleteButtonProps) {
  return (
    <Disabled disabled={disabled}>
      <Button
        onClick={onClick}
        icon={SvgTrash}
        tooltip="Delete"
        prominence="tertiary"
        size="sm"
      />
    </Disabled>
  );
}
