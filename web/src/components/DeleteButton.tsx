import SvgTrash from "@/icons/trash";
import IconButton from "@/refresh-components/buttons/IconButton";

export interface DeleteButtonProps {
  onClick?: (event: React.MouseEvent<HTMLElement>) => void | Promise<void>;
  disabled?: boolean;
}

export function DeleteButton({ onClick, disabled }: DeleteButtonProps) {
  return (
    <IconButton
      onClick={onClick}
      icon={SvgTrash}
      tooltip="Delete"
      disabled={disabled}
      internal
    />
  );
}
