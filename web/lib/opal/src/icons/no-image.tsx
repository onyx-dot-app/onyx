import type { IconProps } from "@opal/types";
const SvgNoImage = ({ size, ...props }: IconProps) => (
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
      d="M11 14L6.06066 9.06072C5.47487 8.47498 4.52513 8.47498 3.93934 9.06072L2 11M11 14L12.5 13.9998C12.9142 13.9998 13.2892 13.832 13.5606 13.5606M11 14L3.5 13.9998C2.67157 13.9998 2 13.3283 2 12.4999V11M2 11V3.49998C2 3.08577 2.16789 2.71078 2.43934 2.43934M1 1L2.43934 2.43934M2.43934 2.43934L13.5606 13.5606M13.5606 13.5606L15 15M10.8033 7.30328C11.1515 7.0286 11.375 6.60288 11.375 6.12494C11.375 5.29653 10.7035 4.62496 9.875 4.62496C9.39706 4.62496 8.97135 4.84847 8.69666 5.19666M14 10.5V3.49998C14 2.67156 13.3285 2 12.5 2H5.5"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgNoImage;
