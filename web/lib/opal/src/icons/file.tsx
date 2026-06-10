import type { IconProps } from "@opal/types";
const SvgFile = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M13.3333 6.00004L8.66667 1.33337H4.00001C3.27378 1.33337 2.66667 1.94048 2.66667 2.66671V13.3334C2.66667 14.0596 3.27378 14.6667 4.00001 14.6667H12C12.7262 14.6667 13.3333 14.0596 13.3333 13.3334V6.00004ZM8.66667 1.33337V6.00004H13.3333"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFile;
