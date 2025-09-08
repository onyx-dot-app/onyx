import React from "react";
import { IconBaseProps, IconType } from "react-icons";
import { FaQuestion } from "react-icons/fa";

interface DynamicIconProps extends IconBaseProps {
  name: string;
}

// Renders a FontAwesome icon dynamically based on the provided name
const DynamicFaIcon: React.FC<DynamicIconProps> = ({ name, ...props }) => {
  const IconComponent = getPreloadedIcon(name);
  return IconComponent ? (
    <IconComponent className="h-4 w-4" {...props} />
  ) : (
    <FaQuestion className="h-4 w-4" {...props} />
  );
};

// Cache for storing preloaded icons
const iconCache: Record<string, IconType> = {};

// Preloads icons asynchronously and stores them in the cache
export async function preloadIcons(iconNames: string[]): Promise<void> {
  const promises = iconNames.map(async (name) => {
    try {
      const iconModule = await import("react-icons/fa");
      const iconName = `Fa${
        name.charAt(0).toUpperCase() + name.slice(1)
      }` as keyof typeof iconModule;
      iconCache[name] = (iconModule[iconName] as IconType) || FaQuestion;
    } catch (error) {
      console.error(`Failed to load icon: ${name}`, error);
      iconCache[name] = FaQuestion;
    }
  });

  await Promise.all(promises);
}

// Retrieves a preloaded icon from the cache
export function getPreloadedIcon(name: string): IconType | undefined {
  return iconCache[name] || FaQuestion;
}

export default DynamicFaIcon;
