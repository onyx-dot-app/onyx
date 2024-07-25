import React, {
  ReactNode,
  useState,
  useEffect,
  useRef,
  createContext,
  useContext,
} from "react";

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

export const TooltipGroup: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const [groupHovered, setGroupHovered] = useState(false);
  const hoverCountRef = useRef(false);

  return (
    <TooltipGroupContext.Provider
      value={{ groupHovered, setGroupHovered, hoverCountRef }}
    >
      <div className="inline-flex">{children}</div>
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
  showTick = false,
  delay = 500,
}: {
  content: string | ReactNode;
  children: JSX.Element;
  large?: boolean;
  line?: boolean;
  light?: boolean;
  showTick?: boolean;
  delay?: number;
  citation?: boolean;
}) => {
  const [isVisible, setIsVisible] = useState(false);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const { groupHovered, setGroupHovered, hoverCountRef } =
    useContext(TooltipGroupContext);

  const showTooltip = () => {
    hoverCountRef.current = true;

    const showDelay = groupHovered ? 0 : delay;
    timeoutRef.current = setTimeout(() => {
      setIsVisible(true);
      setGroupHovered(true);
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

  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return (
    <span className="relative inline-block">
      <span
        className="underline h-full leading-none"
        onMouseEnter={showTooltip}
        onMouseLeave={hideTooltip}
      >
        {children}
      </span>
      {isVisible && (
        <div
          className={`absolute z-10 ${citation ? "max-w-[350px]" : "w-40"} ${large ? "w-96" : line && "max-w-64 w-auto"} 
              left-1/2 transform -translate-x-1/2 mt-2 text-sm 
              ${
                light
                  ? "text-gray-800 bg-background-200"
                  : "text-white bg-background-800"
              } 
              rounded-lg shadow-lg`}
        >
          {showTick && (
            <div
              className={`absolute w-3 h-3 -top-1.5 left-1/2 transform -translate-x-1/2 rotate-45 
                  ${light ? "bg-background-200" : "bg-background-800"}`}
            />
          )}
          <div
            className={` relative ${line ? "" : "flex"} p-2`}
            style={
              line
                ? {
                    whiteSpace: "nowrap",
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }
                : {}
            }
          >
            {content}
          </div>
        </div>
      )}
    </span>
  );
};
