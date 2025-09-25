import { IconType } from "react-icons";

const ICON_SIZE = 15;

export interface HoverableProps {
  icon: IconType;
  onClick?: () => void;
  size?: number;
  active?: boolean;
  hoverText?: string;
}

export function Hoverable({
  icon: Icon,
  active,
  hoverText,
  onClick,
  size = ICON_SIZE,
}: HoverableProps) {
  return (
    <div
      className={`group relative flex items-center overflow-hidden  p-1.5  h-fit rounded-md cursor-pointer transition-all duration-300 ease-in-out hover:bg-background-tint-01`}
      onClick={onClick}
    >
      <div className="flex items-center">
        <Icon
          size={size}
          className="text-text-03 rounded h-fit cursor-pointer"
        />
        {hoverText && (
          <div className="max-w-0 leading-none whitespace-nowrap overflow-hidden transition-all duration-300 ease-in-out group-hover:max-w-xs group-hover:ml-2">
            <span className="text-xs text-text-02">{hoverText}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export interface HoverableIconProps {
  icon: JSX.Element;
  onClick?: () => void;
}

export function HoverableIcon({ icon, onClick }: HoverableIconProps) {
  return (
    <button
      className="hover:bg-background-tint-03 text-text-03 p-1.5 rounded h-fit"
      onClick={onClick}
    >
      {icon}
    </button>
  );
}
