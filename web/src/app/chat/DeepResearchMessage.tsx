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
import { DeepAction, isCollapsible } from "./deepResearchAction";
import {
  DeepProcessAction,
  DeepSendEmail,
  DeepThinkingAction,
  RunCommandAction,
  WebSearchAction,
} from "./DeepActions";

const RenderAction = ({
  action,
  messageId,
  setMessageActionCollapsed,
}: {
  action: DeepAction;
  messageId: number;
  setMessageActionCollapsed?: (
    messageId: number,
    actionId: string,
    collapsed: boolean
  ) => void;
}) => {
  const Inner = ({ action }: { action: DeepAction }): JSX.Element => {
    switch (action.type) {
      case "remove":
        return <div>Remove</div>;
      case "run_command":
        return <RunCommandAction action={action} />;
      case "thinking":
        return <DeepThinkingAction action={action} />;
      case "web_search":
        return <WebSearchAction action={action} />;
      case "email":
        return <DeepSendEmail action={action} />;
      case "process":
        return <DeepProcessAction action={action} />;
      default:
        return action satisfies never; // ensure all deep action types are rendered
    }
  };
  const verticalLine = (
    <div className="h-full w-[2px] min-w-[2px] bg-neutral-500"></div>
  );
  return (
    <div className="mb-4 overflow-x-auto flex gap-2 relative">
      {isCollapsible(action) ? (
        <div className="flex flex-col justify-items-center items-center">
          <div
            className="cursor-pointer select-none text-sm text-neutral-500 hover:text-neutral-300 transition-transform duration-200"
            style={{
              transform: `rotate(${action.collapsed ? "0deg" : "90deg"})`,
            }}
            onClick={() => {
              if (setMessageActionCollapsed) {
                setMessageActionCollapsed(
                  messageId,
                  action.id,
                  !action.collapsed
                );
              }
            }}
          >
            ▶
          </div>
          {!action.collapsed && <div className="flex-grow">{verticalLine}</div>}
        </div>
      ) : (
        <div className="pl-[5px]">{verticalLine}</div>
      )}
      <div className="w-full">{<Inner action={action} />}</div>
    </div>
  );
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
  setMessageActionCollapsed?: (
    messageId: number,
    actionId: string,
    collapsed: boolean
  ) => void;
};

export const DeepResearchMessage = (props: DeepResearchMessageProps) => {
  const actions = props.message.actions ?? [];
  const [parent] = useAutoAnimate();
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
          <div ref={parent} className="py-4">
            {actions.map((action) => (
              <RenderAction
                key={action.id}
                action={action}
                messageId={props.message.messageId}
                setMessageActionCollapsed={props.setMessageActionCollapsed}
              />
            ))}
          </div>
          <div className="w-full py-2">
            <div className="max-w-message-max break-words">
              <div className="w-full">
                <div className="max-w-message-max break-words">
                  {props.content ? (
                    <>
                      {typeof props.content === "string" ? (
                        <div className="overflow-x-visible max-w-content-max">
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
