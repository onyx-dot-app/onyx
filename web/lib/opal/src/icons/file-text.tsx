import type { IconProps } from "@opal/types";
const SvgFileText = ({ size, ...props }: IconProps) => (
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
      d="M13.3333 5.33337L9.33334 1.33337H4.00001C3.27378 1.33337 2.66667 1.94048 2.66667 2.66671V13.3334C2.66667 14.0596 3.27378 14.6667 4.00001 14.6667H12C12.7262 14.6667 13.3333 14.0596 13.3333 13.3334V5.33337ZM9.33334 1.33337L9.33334 5.33337L13.3333 5.33337M10.6667 8.66671H5.33334M10.6667 11.3334H5.33334M6.66667 6.00004H5.33334"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFileText;
