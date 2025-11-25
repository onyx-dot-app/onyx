export interface SvgProps {
  className?: string;
}

export interface IconProps extends React.SVGProps<SVGSVGElement> {
  size?: number | string;
  title?: string;
  color?: string;
}
