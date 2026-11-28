export const GALLERY_IMAGE_ATTR = "data-gallery-image";
export const GALLERY_ALT_ATTR = "data-gallery-alt";
export const GALLERY_ROOT_ATTR = "data-gallery-root";

export interface GalleryImage {
  url: string;
  alt: string;
}

export interface GalleryState {
  images: GalleryImage[];
  index: number;
}

function readImage(node: Element): GalleryImage | null {
  const url = node.getAttribute(GALLERY_IMAGE_ATTR);
  return url ? { url, alt: node.getAttribute(GALLERY_ALT_ATTR) ?? "" } : null;
}

export function collectGallery(trigger: Element | null): GalleryState | null {
  const own = trigger && readImage(trigger);
  if (!trigger || !own) return null;
  const root =
    trigger.closest(`[${GALLERY_ROOT_ATTR}]`) ?? trigger.parentElement;
  const nodes = Array.from(
    root?.querySelectorAll(`[${GALLERY_IMAGE_ATTR}]`) ?? []
  ).filter((node) => readImage(node));
  const images = nodes.flatMap((node) => readImage(node) ?? []);
  const index = nodes.indexOf(trigger);
  return index < 0 ? { images: [own], index: 0 } : { images, index };
}
