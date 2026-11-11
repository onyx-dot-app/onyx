import type { IconProps } from "@opal/types";
const SvgMarkdownFile = ({ size, ...props }: IconProps) => (
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
      d="M2 12.67C2 13.4045 2.59546 14 3.33 14H12.67C13.4045 14 14 13.4045 14 12.67V11M2 3.33C2 2.59546 2.59546 2 3.33 2H12.67C13.4045 2 14 2.59546 14 3.33V5.5M11.5002 5.75V10.2498M13.75 8L11.5002 10.2498L9.2504 8M2 10.25V5.75L4.5 8.25L7 5.75V10.25"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgMarkdownFile;
