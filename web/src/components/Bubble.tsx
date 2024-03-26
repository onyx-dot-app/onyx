export function Bubble({
  isSelected,
  onClick,
  children,
}: {
  isSelected: boolean;
  onClick?: () => void;
  children: string | JSX.Element;
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
    </div>
  );
}
