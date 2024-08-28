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
      className={`group relative flex items-center overflow-hidden  p-1.5  h-fit rounded-md cursor-pointer transition-all duration-300 ease-in-out hover:bg-hover`}
      onClick={onClick}
    >
      <div className="flex items-center ">
        <Icon size={size} className="text-gray-600 shrink-0" />
        {hoverText && (
          <div className="max-w-0 leading-none whitespace-nowrap overflow-hidden transition-all duration-300 ease-in-out group-hover:max-w-xs group-hover:ml-2">
            <span className="text-xs  text-gray-700">{hoverText}</span>
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
      className="hover:bg-hover p-1.5 rounded h-fit cursor-pointer"
      onClick={onClick}
    >
      {icon}
    </div>
  );
};
