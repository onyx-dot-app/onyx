import { CustomCheckbox } from "./CustomCheckbox";

export function Bubble({
  isSelected,
  onClick,
  children,
  showCheckbox = false,
}: {
  isSelected: boolean;
  onClick?: () => void;
  children: string | JSX.Element;
  showCheckbox?: boolean;
}) {
  return (
    <div
      className={
        `
      px-3 
      py-1
      rounded-lg 
      border
      border-border 
      w-fit 
      flex 
      cursor-pointer ` +
        (isSelected ? " bg-hover" : " bg-background hover:bg-hover-light")
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
