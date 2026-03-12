"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgZoomIn, SvgZoomOut } from "@opal/icons";
import { toast } from "@/hooks/useToast";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";

const CANVAS_SIZE = 448;
const OUTPUT_SIZE = 192;
const MIN_ZOOM = 1;
const MAX_ZOOM = 5;
const ZOOM_STEP = 0.25;

interface LogoCropModalProps {
  file: File;
  onApply: (croppedFile: File) => void;
  onCancel: () => void;
}

export default function LogoCropModal({
  file,
  onApply,
  onCancel,
}: LogoCropModalProps) {
  const [imageSrc, setImageSrc] = useState<string | null>(null);
  const [zoom, setZoom] = useState(MIN_ZOOM);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [naturalSize, setNaturalSize] = useState({ w: 0, h: 0 });
  const maskId = useId();
  const dragStartRef = useRef({ x: 0, y: 0, ox: 0, oy: 0 });
  const imageRef = useRef<HTMLImageElement | null>(null);

  useEffect(() => {
    const url = URL.createObjectURL(file);
    setImageSrc(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  const handleImageLoad = useCallback(
    (e: React.SyntheticEvent<HTMLImageElement>) => {
      const img = e.currentTarget;
      setNaturalSize({ w: img.naturalWidth, h: img.naturalHeight });
      imageRef.current = img;
    },
    []
  );

  const getBaseDisplayedSize = useCallback(() => {
    if (naturalSize.w === 0 || naturalSize.h === 0) {
      return { w: CANVAS_SIZE, h: CANVAS_SIZE };
    }
    const shortSide = Math.min(naturalSize.w, naturalSize.h);
    const scale = CANVAS_SIZE / shortSide;
    return {
      w: naturalSize.w * scale,
      h: naturalSize.h * scale,
    };
  }, [naturalSize]);

  const getDisplayedSize = useCallback(() => {
    const baseSize = getBaseDisplayedSize();
    return {
      w: baseSize.w * zoom,
      h: baseSize.h * zoom,
    };
  }, [getBaseDisplayedSize, zoom]);

  const clampOffset = useCallback(
    (ox: number, oy: number) => {
      const { w, h } = getDisplayedSize();
      const maxX = Math.max(0, (w - CANVAS_SIZE) / 2);
      const maxY = Math.max(0, (h - CANVAS_SIZE) / 2);
      return {
        x: Math.max(-maxX, Math.min(maxX, ox)),
        y: Math.max(-maxY, Math.min(maxY, oy)),
      };
    },
    [getDisplayedSize]
  );

  useEffect(() => {
    setOffset((prev) => clampOffset(prev.x, prev.y));
  }, [zoom, clampOffset]);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      e.preventDefault();
      setDragging(true);
      dragStartRef.current = {
        x: e.clientX,
        y: e.clientY,
        ox: offset.x,
        oy: offset.y,
      };
      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [offset]
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!dragging) return;
      const dx = e.clientX - dragStartRef.current.x;
      const dy = e.clientY - dragStartRef.current.y;
      setOffset(
        clampOffset(dragStartRef.current.ox + dx, dragStartRef.current.oy + dy)
      );
    },
    [dragging, clampOffset]
  );

  const handlePointerUp = useCallback(() => {
    setDragging(false);
  }, []);

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = -e.deltaY * 0.003;
    setZoom((z) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z + delta)));
  }, []);

  const handleApply = useCallback(() => {
    if (!imageRef.current || naturalSize.w === 0) return;

    const canvas = document.createElement("canvas");
    canvas.width = OUTPUT_SIZE;
    canvas.height = OUTPUT_SIZE;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      toast.error("Failed to process image. Please try again.");
      return;
    }

    const shortSide = Math.min(naturalSize.w, naturalSize.h);
    const scale = (CANVAS_SIZE / shortSide) * zoom;

    const srcCenterX = naturalSize.w / 2 - offset.x / scale;
    const srcCenterY = naturalSize.h / 2 - offset.y / scale;
    const srcSize = CANVAS_SIZE / scale;

    ctx.drawImage(
      imageRef.current,
      srcCenterX - srcSize / 2,
      srcCenterY - srcSize / 2,
      srcSize,
      srcSize,
      0,
      0,
      OUTPUT_SIZE,
      OUTPUT_SIZE
    );

    const isPng = file.type === "image/png";
    canvas.toBlob(
      (blob) => {
        if (!blob) {
          toast.error("Failed to process image. Please try again.");
          return;
        }
        const cropped = new File(
          [blob],
          file.name.replace(/\.\w+$/, isPng ? ".png" : ".jpg"),
          { type: isPng ? "image/png" : "image/jpeg" }
        );
        onApply(cropped);
      },
      isPng ? "image/png" : "image/jpeg",
      0.92
    );
  }, [file, naturalSize, zoom, offset, onApply]);

  const baseDisplayed = getBaseDisplayedSize();
  const isLandscapeOrSquare = naturalSize.w >= naturalSize.h;

  return (
    <Modal open onOpenChange={(open) => !open && onCancel()}>
      <Modal.Content width="sm" height="fit" preventAccidentalClose={false}>
        <Modal.Header title="Position Logo" onClose={onCancel} />
        <Modal.Body twoTone>
          <div className="flex flex-col items-center w-full">
            <div
              className="relative overflow-hidden select-none"
              style={{
                width: CANVAS_SIZE,
                height: CANVAS_SIZE,
                cursor: dragging ? "grabbing" : "grab",
                touchAction: "none",
              }}
              onPointerDown={handlePointerDown}
              onPointerMove={handlePointerMove}
              onPointerUp={handlePointerUp}
              onPointerCancel={handlePointerUp}
              onWheel={handleWheel}
            >
              {imageSrc && (
                <img
                  src={imageSrc}
                  alt="Logo preview"
                  draggable={false}
                  onLoad={handleImageLoad}
                  className="absolute pointer-events-none"
                  style={{
                    width: isLandscapeOrSquare ? baseDisplayed.w : "auto",
                    height: isLandscapeOrSquare ? "auto" : baseDisplayed.h,
                    maxWidth: "none",
                    left: CANVAS_SIZE / 2 - baseDisplayed.w / 2,
                    top: CANVAS_SIZE / 2 - baseDisplayed.h / 2,
                    transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom})`,
                    transformOrigin: "center center",
                  }}
                />
              )}

              <svg
                className="absolute inset-0 pointer-events-none"
                width={CANVAS_SIZE}
                height={CANVAS_SIZE}
              >
                <defs>
                  <mask id={maskId}>
                    <rect width="100%" height="100%" fill="white" />
                    <circle
                      cx={CANVAS_SIZE / 2}
                      cy={CANVAS_SIZE / 2}
                      r={CANVAS_SIZE / 2 - 1}
                      fill="black"
                    />
                  </mask>
                </defs>
                <rect
                  width="100%"
                  height="100%"
                  fill="rgba(0,0,0,0.55)"
                  mask={`url(#${maskId})`}
                />
                <circle
                  cx={CANVAS_SIZE / 2}
                  cy={CANVAS_SIZE / 2}
                  r={CANVAS_SIZE / 2 - 1}
                  fill="none"
                  stroke="white"
                  strokeWidth="2"
                />
              </svg>
            </div>
          </div>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            left={
              <div className="flex items-center gap-1">
                <Disabled disabled={zoom <= MIN_ZOOM}>
                  <Button
                    prominence="tertiary"
                    size="md"
                    icon={SvgZoomOut}
                    onClick={() =>
                      setZoom((z) => Math.max(MIN_ZOOM, z - ZOOM_STEP))
                    }
                  />
                </Disabled>
                <Text
                  text03
                  mainUiAction
                  className={cn("w-10 text-center select-none")}
                >
                  {Math.round(zoom * 100)}%
                </Text>
                <Disabled disabled={zoom >= MAX_ZOOM}>
                  <Button
                    prominence="tertiary"
                    size="md"
                    icon={SvgZoomIn}
                    onClick={() =>
                      setZoom((z) => Math.min(MAX_ZOOM, z + ZOOM_STEP))
                    }
                  />
                </Disabled>
              </div>
            }
            cancel={
              <Button prominence="secondary" onClick={onCancel}>
                Cancel
              </Button>
            }
            submit={<Button onClick={handleApply}>Apply</Button>}
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
