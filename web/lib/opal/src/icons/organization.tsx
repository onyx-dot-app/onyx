import type { IconProps } from "@/types/icons";

const SvgOrganization = ({ size, ...props }: IconProps) => (
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
      d="M7.5 14H13.5C14.0523 14 14.5 13.5523 14.5 13V6C14.5 5.44772 14.0523 5 13.5 5H7.5M7.5 14V11M7.5 14H4.5M7.5 5V3C7.5 2.44772 7.05228 2 6.5 2H4.5M7.5 5H1.5M7.5 5V8M1.5 5V3C1.5 2.44772 1.94772 2 2.5 2H4.5M1.5 5V8M7.5 8V11M7.5 8H4.5M1.5 8V11M1.5 8H4.5M7.5 11H4.5M1.5 11V13C1.5 13.5523 1.94772 14 2.5 14H4.5M1.5 11H4.5M4.5 2V8M4.5 14V11M4.5 11V8M10 8H12M10 11H12"
      strokeWidth={1}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgOrganization;
