export const GALLERY_IMAGE_ATTR = "data-gallery-image";
export const GALLERY_ROOT_ATTR = "data-gallery-root";

export interface GalleryState {
  urls: string[];
  index: number;
}

export function collectGallery(trigger: Element | null): GalleryState | null {
  const own = trigger?.getAttribute(GALLERY_IMAGE_ATTR);
  if (!trigger || !own) return null;
  const root =
    trigger.closest(`[${GALLERY_ROOT_ATTR}]`) ?? trigger.parentElement;
  const nodes = Array.from(
    root?.querySelectorAll(`[${GALLERY_IMAGE_ATTR}]`) ?? []
  );
  const urls = nodes.flatMap((node) => {
    const url = node.getAttribute(GALLERY_IMAGE_ATTR);
    return url ? [url] : [];
  });
  const index = nodes.indexOf(trigger);
  return index < 0 ? { urls: [own], index: 0 } : { urls, index };
}
