import { IconProps } from "@/icons";

const SvgPlus = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 16 16"
    fill="none"
    {...props}
  >
    <path
      d="M8 2V14M2 8H14"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgPlus;
