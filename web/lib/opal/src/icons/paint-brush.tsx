import type { IconProps } from "@opal/types";
const SvgPaintBrush = ({ size, ...props }: IconProps) => (
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
      d="M8.49998 1.5H5.49998C3.84313 1.5 2.49998 2.84315 2.49998 4.5L2.49999 8.5L2.5 9.61722C2.5 10.1215 2.87553 10.5469 3.37596 10.6095L5.62403 10.8905C6.12446 10.9531 6.49999 11.3785 6.49999 11.8828L6.49999 13C6.49999 13.8284 7.17156 14.5 7.99999 14.5C8.82841 14.5 9.49999 13.8284 9.49999 13L9.49999 11.8828C9.49999 11.3785 9.87553 10.9531 10.376 10.8905L12.624 10.6095C13.1245 10.5469 13.5 10.1215 13.5 9.61721L13.5 8.5M2.49999 8.5H13.5M13.5 8.5L13.5 1.5H11M11 1.5L11 5M11 1.5H8.49998M8.49998 1.5L8.5 4"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgPaintBrush;
