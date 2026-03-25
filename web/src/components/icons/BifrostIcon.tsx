import { JSX } from "react";

export interface BifrostIconProps {
  size?: number;
  className?: string;
}

function BifrostLogo({
  size,
  className,
  fill,
}: Required<BifrostIconProps> & {
  fill: string;
}): JSX.Element {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 37 46"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
      focusable="false"
      preserveAspectRatio="xMidYMid meet"
    >
      <path
        d="M27.6219 46H0V36.8H27.6219V46ZM36.8268 36.8H27.6219V27.6H36.8268V36.8ZM18.4146 27.6H9.2073V18.4H18.4146V27.6ZM36.8268 18.4H27.6219V9.2H36.8268V18.4ZM27.6219 9.2H0V0H27.6219V9.2Z"
        fill={fill}
      />
    </svg>
  );
}

export function BifrostIcon({
  size = 16,
  className = "",
}: BifrostIconProps): JSX.Element {
  return (
    <>
      <BifrostLogo
        size={size}
        className={`${className} dark:hidden`}
        fill="#33C19E"
      />
      <BifrostLogo
        size={size}
        className={`${className} hidden dark:block`}
        fill="white"
      />
    </>
  );
}
