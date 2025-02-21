export function MetadataBadge({
  icon,
  value,
  flexNone,
}: {
  icon?: React.FC<{ size?: number; className?: string }>;
  value: string | JSX.Element;
  flexNone?: boolean;
}) {
  return (
    <div
      className={`
      text-xs 
      text-strong
      flex
      bg-accent-background-hovered 
      rounded-full 
      px-1
      py-0.5 
      w-fit 
      my-auto 
      select-none 
      ${flexNone ? "flex-none" : ""}`}
    >
      {icon &&
        icon({
          size: 12,
          className: flexNone ? "flex-none" : "mr-0.5 my-auto",
        })}
      <p className="max-w-[6rem] text-ellipsis overflow-hidden truncate whitespace-nowrap">
        {value}
      </p>
    </div>
  );
}
