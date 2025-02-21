import { IconType } from "react-icons";

const ICON_SIZE = 15;

export const Hoverable: React.FC<{
  icon: IconType;
  onClick?: () => void;
  size?: number;
  active?: boolean;
  hoverText?: string;
}> = ({ icon: Icon, active, hoverText, onClick, size = ICON_SIZE }) => {
  return (
    <div
      className={`group relative flex items-center overflow-hidden  p-1.5  h-fit rounded-md cursor-pointer transition-all duration-300 ease-in-out hover:bg-accent-background-hovered`}
      onClick={onClick}
    >
      <div className="flex items-center">
        <Icon
          size={size}
          className="dark:text-[#B4B4B4] text-neutral-600  rounded h-fit cursor-pointer"
        />
        {hoverText && (
          <div className="max-w-0 leading-none whitespace-nowrap overflow-hidden transition-all duration-300 ease-in-out group-hover:max-w-xs group-hover:ml-2">
            <span className="text-xs text-text-700">{hoverText}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export const HoverableIcon: React.FC<{
  icon: JSX.Element;
  onClick?: () => void;
}> = ({ icon, onClick }) => {
  return (
    <div
      className="hover:bg-background-chat-hover dark:text-[#B4B4B4] text-neutral-600 p-1.5 rounded h-fit cursor-pointer"
      onClick={onClick}
    >
      {icon}
    </div>
  );
};
