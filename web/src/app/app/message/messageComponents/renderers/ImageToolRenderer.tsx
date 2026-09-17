import { useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import { SvgImage } from "@opal/icons";
import { ResponseItem } from "@/app/app/services/streamingModels";
import {
  MessageRenderer,
  RenderType,
} from "@/app/app/message/messageComponents/interfaces";
import { InMessageImage } from "@/app/app/components/files/images/InMessageImage";
import GeneratingImageDisplay from "@/app/app/components/tools/GeneratingImageDisplay";
import {
  isComplete as itemsComplete,
  toolMetadata,
} from "@/app/app/services/responseItems";

function constructCurrentImageState(items: ResponseItem[]) {
  return {
    prompt: "",
    images: toolMetadata(items, "image_generation_result").flatMap(
      (value) => value.generated_images
    ),
    isGenerating: !itemsComplete(items),
    isComplete: itemsComplete(items),
    error: items.some((item) => item.content.status === "error"),
  };
}

export const ImageToolRenderer: MessageRenderer<ResponseItem, {}> = ({
  items,
  onComplete,
  renderType,
  children,
}) => {
  const t = useTranslations("chat.messages");
  const { prompt, images, isGenerating, isComplete, error } =
    constructCurrentImageState(items);

  useEffect(() => {
    if (isComplete) {
      onComplete();
    }
  }, [isComplete]);

  const status = useMemo(() => {
    if (isComplete) {
      return t("imageTool.generatedStatus.text", { count: images.length });
    }
    if (isGenerating) {
      return t("imageTool.generatingStatus.text");
    }
    return null;
  }, [isComplete, isGenerating, images.length, t]);

  // Render based on renderType
  if (renderType === RenderType.FULL) {
    // Full rendering with title header and content below
    // Loading state - when generating
    if (isGenerating) {
      return children([
        {
          icon: SvgImage,
          status: t("imageTool.generatingImagesStatus.text"),
          supportsCollapsible: false,
          content: (
            <div className="flex flex-col">
              <div>
                <GeneratingImageDisplay isCompleted={false} />
              </div>
            </div>
          ),
        },
      ]);
    }

    // Complete state - show images
    if (isComplete) {
      return children([
        {
          icon: SvgImage,
          status: t("imageTool.generatedStatus.text", { count: images.length }),
          supportsCollapsible: false,
          content: (
            <div className="flex flex-col my-1">
              {images.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {images.map((image, index: number) => (
                    <div
                      key={image.file_id || index}
                      className="transition-all group"
                    >
                      {image.file_id && (
                        <InMessageImage
                          fileId={image.file_id}
                          shape={image.shape}
                        />
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-4 text-center text-gray-500 dark:text-gray-400 ms-7">
                  <SvgImage className="w-6 h-6 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">{t("imageTool.emptyState.text")}</p>
                </div>
              )}
            </div>
          ),
        },
      ]);
    }

    // Fallback (shouldn't happen in normal flow)
    return children([
      {
        icon: SvgImage,
        status: status,
        supportsCollapsible: false,
        content: <div></div>,
      },
    ]);
  }

  // Highlight/Short rendering
  if (isGenerating) {
    return children([
      {
        icon: SvgImage,
        status: t("imageTool.generatingStatus.text"),
        supportsCollapsible: false,
        content: (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <div className="flex gap-0.5">
              <div className="w-1 h-1 bg-current rounded-full animate-pulse"></div>
              <div
                className="w-1 h-1 bg-current rounded-full animate-pulse"
                style={{ animationDelay: "0.1s" }}
              ></div>
              <div
                className="w-1 h-1 bg-current rounded-full animate-pulse"
                style={{ animationDelay: "0.2s" }}
              ></div>
            </div>
            <span>{t("imageTool.generatingStatus.text")}</span>
          </div>
        ),
      },
    ]);
  }

  if (error) {
    return children([
      {
        icon: SvgImage,
        status: t("imageTool.failedStatus.text"),
        supportsCollapsible: false,
        content: (
          <div className="text-sm text-red-600 dark:text-red-400">
            {t("imageTool.failedStatus.text")}
          </div>
        ),
      },
    ]);
  }

  if (isComplete && images.length > 0) {
    return children([
      {
        icon: SvgImage,
        status: t("imageTool.generatedStatus.text", { count: images.length }),
        supportsCollapsible: false,
        content: (
          <div className="text-sm text-muted-foreground">
            {t("imageTool.generatedStatus.text", { count: images.length })}
          </div>
        ),
      },
    ]);
  }

  return children([
    {
      icon: SvgImage,
      status: t("imageTool.defaultStatus.text"),
      supportsCollapsible: false,
      content: (
        <div className="text-sm text-muted-foreground">
          {t("imageTool.defaultStatus.text")}
        </div>
      ),
    },
  ]);
};
