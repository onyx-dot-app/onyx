import type { IconProps } from "@opal/types";
const SvgMusicFile = ({ size, ...props }: IconProps) => (
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
      d="M9.5 9.74997C9.5 10.7165 8.7165 11.5 7.75 11.5C6.7835 11.5 6 10.7165 6 9.74997C6 8.78347 6.7835 7.99997 7.75 7.99997C8.7165 7.99997 9.5 8.78347 9.5 9.74997ZM9.5 9.74997V4.58925L10.75 4.25431M2 12.67V3.33C2 2.59546 2.59546 2 3.33 2H12.67C13.4045 2 14 2.59546 14 3.33V12.67C14 13.4045 13.4045 14 12.67 14H3.33C2.59546 14 2 13.4045 2 12.67Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgMusicFile;
