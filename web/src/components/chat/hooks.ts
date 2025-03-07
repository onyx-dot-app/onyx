import { Dispatch, SetStateAction, useEffect, useRef } from "react";

interface UseSidebarVisibilityProps {
  sidebarVisible: boolean;
  sidebarElementRef: React.RefObject<HTMLElement>;
  showDocSidebar: boolean;
  setShowDocSidebar: Dispatch<SetStateAction<boolean>>;
  mobile?: boolean;
  setToggled?: () => void;
  isAnonymousUser?: boolean;
}

export const useSidebarVisibility = ({
  sidebarVisible,
  sidebarElementRef,
  setShowDocSidebar,
  setToggled,
  showDocSidebar,
  mobile,
  isAnonymousUser,
}: UseSidebarVisibilityProps) => {
  const xPosition = useRef(0);

  useEffect(() => {
    const handleEvent = (event: MouseEvent) => {
      if (isAnonymousUser) {
        return;
      }
      const currentXPosition = event.clientX;
      xPosition.current = currentXPosition;

      const sidebarRect = sidebarElementRef.current?.getBoundingClientRect();

      if (sidebarRect && sidebarElementRef.current) {
        const isWithinSidebar =
          currentXPosition >= sidebarRect.left &&
          currentXPosition <= sidebarRect.right &&
          event.clientY >= sidebarRect.top &&
          event.clientY <= sidebarRect.bottom;

        const sidebarStyle = window.getComputedStyle(sidebarElementRef.current);
        const isVisible = sidebarStyle.opacity !== "0";
        if (isWithinSidebar && isVisible) {
          if (!mobile) {
            setShowDocSidebar(true);
          }
        }

        if (mobile && !isWithinSidebar && setToggled) {
          setToggled();
          return;
        }

        if (
          currentXPosition > 100 &&
          showDocSidebar &&
          !isWithinSidebar &&
          !sidebarVisible
        ) {
          setTimeout(() => {
            setShowDocSidebar((showDocSidebar) => {
              // Account for possition as point in time of
              return !(xPosition.current > sidebarRect.right);
            });
          }, 200);
        } else if (currentXPosition < 100 && !showDocSidebar) {
          if (!mobile) {
            setShowDocSidebar(true);
          }
        }
      }
    };

    const handleMouseLeave = () => {
      if (!mobile) {
        setShowDocSidebar(false);
      }
    };
    if (!mobile) {
      document.addEventListener("mousemove", handleEvent);
      document.addEventListener("mouseleave", handleMouseLeave);
    }

    return () => {
      if (!mobile) {
        document.removeEventListener("mousemove", handleEvent);
        document.removeEventListener("mouseleave", handleMouseLeave);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showDocSidebar, sidebarVisible, sidebarElementRef, mobile]);

  return { showDocSidebar };
};
