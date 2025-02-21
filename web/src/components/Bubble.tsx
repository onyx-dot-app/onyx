import { CustomCheckbox } from "./CustomCheckbox";

export function Bubble({
  isSelected,
  onClick,
  children,
  showCheckbox = false,
  notSelectable = false,
}: {
  isSelected: boolean;
  onClick?: () => void;
  children: string | JSX.Element;
  showCheckbox?: boolean;
  notSelectable?: boolean;
}) {
  return (
    <div
      className={
        `
      px-1.5
      py-1
      rounded-lg 
      border
      border-border 
      w-fit 
      flex` +
        (notSelectable
          ? " bg-background cursor-default"
          : isSelected
            ? " bg-accent-background-hovered cursor-pointer"
            : " bg-background hover:bg-accent-background cursor-pointer")
      }
      onClick={onClick}
    >
      <div className="my-auto">{children}</div>
      {showCheckbox && (
        <div className="pl-2 my-auto">
          <CustomCheckbox checked={isSelected} onChange={() => null} />
        </div>
      )}
    </div>
  );
}
