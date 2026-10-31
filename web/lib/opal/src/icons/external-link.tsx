import type { IconProps } from "@opal/types";
const SvgExternalLink = ({ size, ...props }: IconProps) => (
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
      d="M12 8.66667V12.6667C12 13.3929 11.3929 14 10.6667 14H3.33333C2.60711 14 2 13.3929 2 12.6667V5.33333C2 4.60711 2.60711 4 3.33333 4H7.33333M14 6V2H10M14 2L6.66667 9.33333"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgExternalLink;
