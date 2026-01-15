import type { SVGProps } from "react";

export interface IconProps extends SVGProps<SVGSVGElement> {
  className?: string;
  size?: number;
  title?: string;
  color?: string;
}
