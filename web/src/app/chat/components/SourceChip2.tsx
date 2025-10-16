import Truncated from "@/refresh-components/texts/Truncated";
import { XIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/utils";

interface SourceChip2Props {
  icon?: React.ReactNode;
  title: string;
  onRemove?: () => void;
  onClick?: () => void;
  includeAnimation?: boolean;
}

export function SourceChip2({
  icon,
  title,
  onRemove,
  onClick,
  includeAnimation,
}: SourceChip2Props) {
  const [isNew, setIsNew] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => setIsNew(false), 300);
    return () => clearTimeout(timer);
  }, []);

  return (
    <button
      onClick={onClick}
      className={cn(
        "max-w-[15rem] p-spacing-inline bg-background-tint-03 hover:bg-background-tint-04 rounded-full justify-center items-center flex flex-row transition-colors duration-200",
        includeAnimation && isNew && "animate-fade-in-scale"
      )}
    >
      {icon && (
        <div className="w-[17px] h-4 p-[3px] flex-col justify-center items-center gap-2.5 inline-flex">
          {icon}
        </div>
      )}
      <Truncated text03 secondaryBody>
        {title}
      </Truncated>
      {onRemove && (
        <XIcon
          size={12}
          className="ml-2 cursor-pointer"
          onClick={(e: React.MouseEvent<SVGSVGElement>) => {
            e.stopPropagation();
            onRemove();
          }}
        />
      )}
    </button>
  );
}
