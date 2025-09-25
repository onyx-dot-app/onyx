interface BasicClickableProps {
  children: string | JSX.Element;
  onClick?: () => void;
  inset?: boolean;
  fullWidth?: boolean;
  className?: string;
}

export function BasicClickable({
  children,
  onClick,
  fullWidth = false,
  inset,
  className,
}: BasicClickableProps) {
  return (
    <button
      onClick={onClick}
      className={`
        border 
        border-border
        rounded
        font-medium 
        text-text-02 
        text-sm
        relative
        px-1 py-1.5
        h-full
        bg-background
        select-none
        overflow-hidden
        hover:bg-background-tint-01
        ${fullWidth ? "w-full" : ""}
        ${className ? className : ""}
        `}
    >
      {children}
    </button>
  );
}

interface EmphasizedClickableProps {
  children: string | JSX.Element;
  onClick?: () => void;
  fullWidth?: boolean;
  size?: "sm" | "md" | "lg";
}

export function EmphasizedClickable({
  children,
  onClick,
  fullWidth = false,
  size = "md",
}: EmphasizedClickableProps) {
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
        bg-background-tint-02
        border-1 border-border-02 border bg-background-neutral-01 
        text-sm
        rounded-lg
        hover:bg-background-tint-03
    `}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

interface BasicSelectableProps {
  children: string | JSX.Element;
  selected: boolean;
  hasBorder?: boolean;
  fullWidth?: boolean;
  removeColors?: boolean;
  padding?: "none" | "normal" | "extra";
  isDragging?: boolean;
  isHovered?: boolean;
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
}: BasicSelectableProps) {
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
              ? "bg-background-tint-02"
              : selected
                ? "bg-background-tint-01"
                : isHovered
                  ? "bg-background-tint-01"
                  : ""
            : ""
        }
        ${fullWidth ? "w-full" : ""}`}
    >
      {children}
    </div>
  );
}
