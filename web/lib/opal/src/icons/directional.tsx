import type { IconFunctionComponent, IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import SvgArrowLeftRaw from "@opal/icons/arrow-left";
import SvgArrowLeftDotRaw from "@opal/icons/arrow-left-dot";
import SvgArrowRightRaw from "@opal/icons/arrow-right";
import SvgArrowRightCircleRaw from "@opal/icons/arrow-right-circle";
import SvgArrowRightDotRaw from "@opal/icons/arrow-right-dot";
import SvgArrowWallLeftRaw from "@opal/icons/arrow-wall-left";
import SvgArrowWallRightRaw from "@opal/icons/arrow-wall-right";
import SvgChevronLeftRaw from "@opal/icons/chevron-left";
import SvgChevronRightRaw from "@opal/icons/chevron-right";

// Navigation icons mirror under RTL (Material bidirectionality), wrapped
// here so generated icon files stay untouched and every barrel consumer
// inherits it. Media, clock, and refresh icons never mirror.
function mirrored(Icon: IconFunctionComponent): IconFunctionComponent {
  return function MirroredIcon({ className, ...props }: IconProps) {
    return <Icon className={cn("rtl:-scale-x-100", className)} {...props} />;
  };
}

export const SvgArrowLeft = mirrored(SvgArrowLeftRaw);
export const SvgArrowLeftDot = mirrored(SvgArrowLeftDotRaw);
export const SvgArrowRight = mirrored(SvgArrowRightRaw);
export const SvgArrowRightCircle = mirrored(SvgArrowRightCircleRaw);
export const SvgArrowRightDot = mirrored(SvgArrowRightDotRaw);
export const SvgArrowWallLeft = mirrored(SvgArrowWallLeftRaw);
export const SvgArrowWallRight = mirrored(SvgArrowWallRightRaw);
export const SvgChevronLeft = mirrored(SvgChevronLeftRaw);
export const SvgChevronRight = mirrored(SvgChevronRightRaw);
