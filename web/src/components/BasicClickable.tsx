export function BasicClickable({
  children,
  onClick,
  fullWidth = false,
  inset,
  className,
}: {
  children: string | JSX.Element;
  onClick?: () => void;
  inset?: boolean;
  fullWidth?: boolean;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`
        border 
        border-border
        rounded
        font-medium 
        text-text-darker 
        text-sm
        relative
        px-1 py-1.5
        h-full
        bg-background
        select-none
        overflow-hidden
        hover:bg-accent-background
        ${fullWidth ? "w-full" : ""}
        ${className ? className : ""}
        `}
    >
      {children}
    </button>
  );
}

export function EmphasizedClickable({
  children,
  onClick,
  fullWidth = false,
  size = "md",
}: {
  children: string | JSX.Element;
  onClick?: () => void;
  fullWidth?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  return (
    <button
      className={`
        inline-flex 
        items-center 
        justify-center 
        flex-shrink-0 
        font-medium 
        ${
          size === "sm"
            ? `p-1`
            : size === "md"
              ? `min-h-[38px]  py-1 px-3`
              : `min-h-[42px] py-2 px-4`
        }
        w-fit 
        bg-accent-background-hovered
        border-1 border-border-medium border bg-background-100 
        text-sm
        rounded-lg
        hover:bg-background-125
    `}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function BasicSelectable({
  children,
  selected,
  hasBorder,
  fullWidth = false,
  padding = "normal",
  removeColors = false,
  isDragging = false,
  isHovered,
}: {
  children: string | JSX.Element;
  selected: boolean;
  hasBorder?: boolean;
  fullWidth?: boolean;
  removeColors?: boolean;
  padding?: "none" | "normal" | "extra";
  isDragging?: boolean;
  isHovered?: boolean;
}) {
  return (
    <div
      className={`
        rounded
        font-medium 
        text-sm
        truncate
        px-2
        ${padding == "normal" && "p-1"}
        ${padding == "extra" && "p-1.5"}
        select-none
        ${hasBorder ? "border border-border" : ""}
        ${
          !removeColors
            ? isDragging
              ? "bg-background-chat-hover"
              : selected
                ? "bg-background-chat-selected"
                : isHovered
                  ? "bg-background-chat-hover"
                  : "hover:bg-background-chat-hover"
            : ""
        }
        ${fullWidth ? "w-full" : ""}`}
    >
      {children}
    </div>
  );
}
