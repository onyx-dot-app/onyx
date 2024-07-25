import { IconProps } from "@tremor/react";
import { IconType } from "react-icons";

const ICON_SIZE = 15;

export const Hoverable: React.FC<{
  icon: IconType;
  onClick?: () => void;
  size?: number;
}> = ({ icon, onClick, size = ICON_SIZE }) => {
  return (
    <div
      className="hover:bg-hover p-1.5 rounded h-fit cursor-pointer"
      onClick={onClick}
    >
      {icon({ size: size, className: "my-auto" })}
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
