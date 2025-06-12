"use client";

import { Message } from "./interfaces";
import { useAutoAnimate } from "@formkit/auto-animate/react";
import { AIMessage } from "./message/Messages";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import {
  CustomTooltip,
  TooltipGroup,
} from "@/components/tooltip/CustomTooltip";
import { CopyButton } from "@/components/CopyButton";
import { HoverableIcon } from "@/components/Hoverable";
import { DislikeFeedback, LikeFeedback } from "@/components/icons/icons";
import { useContext } from "react";
import { SettingsContext } from "@/components/settings/SettingsProvider";
import { DeepAction } from "./deepResearchAction";

const RenderAction = ({ action }: { action: DeepAction }) => {
  return <div>{action.type}</div>;
};

type DeepResearchMessageProps = Pick<
  Parameters<typeof AIMessage>[0],
  | "isComplete"
  | "removePadding"
  | "shared"
  | "query"
  | "content"
  | "alternativeAssistant"
  | "currentPersona"
  | "files"
  | "handleFeedback"
  | "isActive"
  | "onMessageSelection"
  | "otherMessagesCanSwitchTo"
> & {
  message: Message;
};

export const DeepResearchMessage = (props: DeepResearchMessageProps) => {
  const actions = props.message.actions ?? [];
  const settings = useContext(SettingsContext);
  const [parent, enableAnimations] = useAutoAnimate(/* optional config */);
  return (
    <div
      id={props.isComplete ? "onyx-ai-message" : undefined}
      className={`py-5 ml-4 lg:px-5 relative flex
        
        ${props.removePadding && "!pl-24 -mt-12"}`}
    >
      <div
        className={`mx-auto p-4 bg-neutral-700 shadow rounded ${
          props.shared ? "w-full" : "w-[90%]"
        }  max-w-message-max`}
      >
        <div className={`lg:mr-12 ${!props.shared && "mobile:ml-0"}`}>
          <div className="flex gap-2 items-start">
            {!props.removePadding && (
              <AssistantIcon
                className="mobile:hidden"
                size={24}
                assistant={props.alternativeAssistant || props.currentPersona}
              />
            )}
            Deep Research
          </div>
          <div ref={parent} className="py-2">
            {actions.map((action, index) => (
              <RenderAction key={index} action={action} />
            ))}
          </div>
          <div className="w-full py-2">
            <div className="max-w-message-max break-words">
              <div className="w-full">
                <div className="max-w-message-max break-words">
                  {/* Only show the message content once thinking is complete or if there's no thinking */}
                  {props.content ? (
                    <>
                      {typeof props.content === "string" ? (
                        <div className="overflow-x-visible max-w-content-max">
                          {/* <div */}
                          {/*   ref={markdownRef} */}
                          {/*   className="focus:outline-none cursor-text select-text" */}
                          {/*   onCopy={(e) => handleCopy(e, markdownRef)} */}
                          {/* > */}
                          {/*   {renderedMarkdown} */}
                          {/* </div> */}
                          {props.content}
                        </div>
                      ) : (
                        <div>{props.content}</div>
                      )}
                    </>
                  ) : props.isComplete ? null : (
                    <></>
                  )}
                </div>

                {!props.removePadding &&
                  props.handleFeedback &&
                  (props.isActive ? (
                    <div
                      className={`
                        flex md:flex-row gap-x-0.5 mt-1
                        transition-transform duration-300 ease-in-out
                        transform opacity-100 "
                  `}
                    >
                      <TooltipGroup>
                        <CustomTooltip showTick line content="Copy">
                          <CopyButton
                            copyAllFn={
                              () => null
                              // copyAll(
                              //   finalContentProcessed as string,
                              //   markdownRef
                              // )
                            }
                          />
                        </CustomTooltip>
                        {props.handleFeedback && (
                          <>
                            <CustomTooltip
                              showTick
                              line
                              content="Good response"
                            >
                              <HoverableIcon
                                icon={<LikeFeedback />}
                                // @ts-ignore
                                onClick={() => props!.handleFeedback("like")}
                              />
                            </CustomTooltip>
                            <CustomTooltip showTick line content="Bad response">
                              <HoverableIcon
                                icon={<DislikeFeedback size={16} />}
                                onClick={() =>
                                  // @ts-ignore
                                  props.handleFeedback("dislike")
                                }
                              />
                            </CustomTooltip>
                          </>
                        )}
                      </TooltipGroup>
                    </div>
                  ) : null)}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
