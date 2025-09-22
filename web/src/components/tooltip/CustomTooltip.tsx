import React, {
  ReactNode,
  useState,
  useEffect,
  useRef,
  createContext,
  useContext,
} from "react";
import { createPortal } from "react-dom";

// Create a context for the tooltip group
const TooltipGroupContext = createContext<{
  setGroupHovered: React.Dispatch<React.SetStateAction<boolean>>;
  groupHovered: boolean;
  hoverCountRef: React.MutableRefObject<boolean>;
}>({
  setGroupHovered: () => {},
  groupHovered: false,
  hoverCountRef: { current: false },
});

export const TooltipGroup: React.FC<{
  children: React.ReactNode;
  gap?: string;
}> = ({ children, gap }) => {
  const [groupHovered, setGroupHovered] = useState(false);
  const hoverCountRef = useRef(false);

  return (
    <TooltipGroupContext.Provider
      value={{ groupHovered, setGroupHovered, hoverCountRef }}
    >
      <div className={`inline-flex ${gap}`}>{children}</div>
    </TooltipGroupContext.Provider>
  );
};

export const CustomTooltip = ({
  content,
  children,
  large,
  light,
  citation,
  line,
  medium,
  wrap,
  showTick = false,
  delay = 300,
  position = "bottom",
  disabled = false,
  className,
}: {
  medium?: boolean;
  content: string | ReactNode;
  children: JSX.Element;
  large?: boolean;
  line?: boolean;
  light?: boolean;
  showTick?: boolean;
  delay?: number;
  wrap?: boolean;
  citation?: boolean;
  position?: "top" | "bottom";
  disabled?: boolean;
  className?: string;
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const [tooltipPosition, setTooltipPosition] = useState({ top: 0, left: 0 });
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const triggerRef = useRef<HTMLSpanElement>(null);

  const { groupHovered, setGroupHovered, hoverCountRef } =
    useContext(TooltipGroupContext);

  const showTooltip = () => {
    hoverCountRef.current = true;

    const showDelay = groupHovered ? 0 : delay;
    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
      setGroupHovered(true);
      updateTooltipPosition();
    }, showDelay);
  };

  const hideTooltip = () => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    hoverCountRef.current = false;
    setIsVisible(false);
    setTimeout(() => {
      if (!hoverCountRef.current) {
        setGroupHovered(false);
      }
    }, 100);
  };

  const updateTooltipPosition = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const scrollX = window.scrollX || window.pageXOffset;
      const scrollY = window.scrollY || window.pageYOffset;

      setTooltipPosition({
        top: (position === "top" ? rect.top - 10 : rect.bottom + 10) + scrollY,
        left: rect.left + rect.width / 2 + scrollX,
      });
    }
  };

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return (
    <>
      <span
        ref={triggerRef}
        className={`relative inline-block ${className}`}
        onMouseEnter={showTooltip}
        onMouseLeave={hideTooltip}
        onMouseDown={hideTooltip}
        onClick={hideTooltip}
      >
        {children}
      </span>
      {isVisible &&
        !disabled &&
        createPortal(
          <div
            className={`fixed z-[1000] overflow-hidden rounded-md text-neutral-50 
              ${className}
              ${citation ? "max-w-[350px]" : "max-w-40"} ${
                large ? (medium ? "w-88" : "w-96") : line && "max-w-64 w-auto"
              } 
            transform -translate-x-1/2 text-xs
            ${
              light
                ? "bg-neutral-200 dark:bg-neutral-800 text-neutral-900 dark:text-neutral-50"
                : "bg-neutral-900 dark:bg-neutral-200 text-neutral-50 dark:text-neutral-900"
            } 
            px-2 py-1.5 shadow-md animate-in fade-in-0 zoom-in-95 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2`}
            style={{
              top: `${tooltipPosition.top}px`,
              left: `${tooltipPosition.left}px`,
            }}
          >
            {showTick && (
              <div
                className={`absolute w-2 h-2 ${
                  position === "top" ? "bottom-1" : "-top-1"
                } left-1/2 transform -translate-x-1/2 rotate-45 
                ${
                  light
                    ? "bg-neutral-200 dark:bg-neutral-800"
                    : "bg-neutral-900 dark:bg-neutral-200"
                }`}
              />
            )}
            <div
              className={`flex-wrap ${wrap && "w-full"} relative ${
                line ? "" : "flex"
              } p-0`}
              style={
                line || wrap
                  ? {
                      whiteSpace: wrap ? "normal" : "nowrap",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                    }
                  : {}
              }
            >
              {content}
            </div>
          </div>,
          document.body
        )}
    </>
  );
};
