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
  delay = 500,
  position = "bottom",
  disabled = false,
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
      setTooltipPosition({
        top: position === "top" ? rect.top - 10 : rect.bottom + 10,
        left: rect.left + rect.width / 2,
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
        className="relative inline-block"
        onMouseEnter={showTooltip}
        onMouseLeave={hideTooltip}
      >
        {children}
      </span>
      {isVisible &&
        !disabled &&
        createPortal(
          <div
            className={`min-w-8 fixed z-[1000] ${
              citation ? "max-w-[350px]" : "w-40"
            } ${large ? (medium ? "w-88" : "w-96") : line && "max-w-64 w-auto"} 
            transform -translate-x-1/2 text-sm 
            ${
              light
                ? "text-text-800 bg-background-200"
                : "text-white bg-background-800"
            } 
            rounded-lg shadow-lg`}
            style={{
              top: `${tooltipPosition.top}px`,
              left: `${tooltipPosition.left}px`,
            }}
          >
            {showTick && (
              <div
                className={`absolute w-3 h-3 ${
                  position === "top" ? "bottom-1.5" : "-top-1.5"
                } left-1/2 transform -translate-x-1/2 rotate-45 
                ${light ? "bg-background-200" : "bg-background-800"}`}
              />
            )}
            <div
              className={`flex-wrap ${wrap && "w-full"} relative ${
                line ? "" : "flex"
              } p-2`}
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
