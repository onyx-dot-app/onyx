"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Cropper, { type Area, type Point } from "react-easy-crop";
import { BasicModalFooter, Button, Modal } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { SvgMinus, SvgPlus } from "@opal/icons";
import { PaneSlider } from "@/sections/model-selector/setting-controls";

const MIN_ZOOM = 1;
const MAX_ZOOM = 3;
const SLIDER_ZOOM_STEP = 0.05;
const BUTTON_ZOOM_STEP = 0.25;
/** Side of the uploaded square. The server stores photos at this size. */
const OUTPUT_SIZE_PX = 512;
const INITIAL_CROP: Point = { x: 0, y: 0 };

interface ProfilePhotoCropModalProps {
  file: File;
  onCancel: () => void;
  /** Receives the cropped square as a PNG. */
  onSave: (photo: File) => void;
}

export default function ProfilePhotoCropModal({
  file,
  onCancel,
  onSave,
}: ProfilePhotoCropModalProps) {
  const t = useTranslations("settings");
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [crop, setCrop] = useState<Point>(INITIAL_CROP);
  const [zoom, setZoom] = useState(MIN_ZOOM);
  const [cropPixels, setCropPixels] = useState<Area | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  async function handleSave() {
    if (!imageUrl || !cropPixels) return;
    setIsSaving(true);
    try {
      const image = new Image();
      image.src = imageUrl;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = OUTPUT_SIZE_PX;
      canvas.height = OUTPUT_SIZE_PX;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Canvas 2D context is not available");
      context.imageSmoothingQuality = "high";
      context.drawImage(
        image,
        cropPixels.x,
        cropPixels.y,
        cropPixels.width,
        cropPixels.height,
        0,
        0,
        OUTPUT_SIZE_PX,
        OUTPUT_SIZE_PX
      );
      const blob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, "image/png")
      );
      if (!blob) throw new Error("Could not encode the cropped photo");
      onSave(new File([blob], "profile.png", { type: "image/png" }));
    } catch (error) {
      console.error(error);
      toast.error(t("profile.photo.toasts.updateFailed"));
      setIsSaving(false);
    }
  }

  return (
    <Modal open onOpenChange={(open) => !open && !isSaving && onCancel()}>
      <Modal.Content width="sm">
        <Modal.Header
          title={t("profile.photo.cropModal.title")}
          description={t("profile.photo.cropModal.description")}
          // A running save would still upload after the dialog closed.
          onClose={isSaving ? undefined : onCancel}
        />
        <Modal.Body>
          <Section gap={1}>
            <div className="relative h-72 w-full overflow-hidden rounded-12">
              {imageUrl && (
                <Cropper
                  image={imageUrl}
                  crop={crop}
                  zoom={zoom}
                  minZoom={MIN_ZOOM}
                  maxZoom={MAX_ZOOM}
                  aspect={1}
                  cropShape="round"
                  showGrid={false}
                  onCropChange={setCrop}
                  onZoomChange={setZoom}
                  // Fires for every crop change, including Reset. The
                  // crop-complete event misses a crop-only update.
                  onCropAreaChange={(_area, areaPixels) =>
                    setCropPixels(areaPixels)
                  }
                  mediaProps={{
                    alt: "",
                    // A damaged file of an allowed type does not decode.
                    onError: () => {
                      toast.error(t("profile.photo.errors.invalidType"));
                      onCancel();
                    },
                  }}
                  cropperProps={{
                    role: "group",
                    "aria-label": t("profile.photo.cropModal.area.ariaLabel"),
                  }}
                />
              )}
            </div>
            <Section flexDirection="row" gap={0.5} height="auto">
              <Button
                icon={SvgMinus}
                prominence="tertiary"
                size="sm"
                aria-label={t("profile.photo.cropModal.zoomOut.ariaLabel")}
                disabled={zoom <= MIN_ZOOM}
                onClick={() =>
                  setZoom(Math.max(MIN_ZOOM, zoom - BUTTON_ZOOM_STEP))
                }
              />
              <PaneSlider
                value={zoom}
                min={MIN_ZOOM}
                max={MAX_ZOOM}
                step={SLIDER_ZOOM_STEP}
                aria-label={t("profile.photo.cropModal.zoom.ariaLabel")}
                onValueChange={setZoom}
              />
              <Button
                icon={SvgPlus}
                prominence="tertiary"
                size="sm"
                aria-label={t("profile.photo.cropModal.zoomIn.ariaLabel")}
                disabled={zoom >= MAX_ZOOM}
                onClick={() =>
                  setZoom(Math.min(MAX_ZOOM, zoom + BUTTON_ZOOM_STEP))
                }
              />
            </Section>
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            left={
              <Button
                prominence="tertiary"
                onClick={() => {
                  setCrop(INITIAL_CROP);
                  setZoom(MIN_ZOOM);
                }}
              >
                {t("profile.photo.cropModal.reset.label")}
              </Button>
            }
            cancel={
              <Button
                prominence="secondary"
                onClick={onCancel}
                disabled={isSaving}
              >
                {t("profile.photo.cropModal.cancel.label")}
              </Button>
            }
            submit={
              <Button
                disabled={isSaving || !cropPixels}
                onClick={() => void handleSave()}
              >
                {t("profile.photo.cropModal.save.label")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
