"use client";

import { ArrayHelpers, ErrorMessage, Field, useFormikContext } from "formik";

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@radix-ui/react-tooltip";

import { useEffect } from "react";
import { FiInfo, FiTrash2, FiPlus } from "react-icons/fi";
import { StarterMessage } from "./interfaces";
import { Label } from "@/components/admin/connectors/Field";

export default function StarterMessagesList({
  values,
  arrayHelpers,
  isRefreshing,
  touchStarterMessages,
}: {
  values: StarterMessage[];
  arrayHelpers: ArrayHelpers;
  isRefreshing: boolean;
  touchStarterMessages: () => void;
}) {
  const { handleChange } = useFormikContext();

  // Group starter messages into rows of 2 for display purposes
  const rows = values.reduce((acc: StarterMessage[][], curr, i) => {
    if (i % 2 === 0) acc.push([curr]);
    else acc[acc.length - 1].push(curr);
    return acc;
  }, []);

  const canAddMore = values.length <= 6;

  return (
    <div className="mt-4 flex flex-col gap-6">
      {rows.map((row, rowIndex) => (
        <div key={rowIndex} className="flex items-start gap-4">
          <div className="grid grid-cols-2 gap-6 w-full xl:w-fit">
            {row.map((starterMessage, colIndex) => (
              <div
                key={rowIndex * 2 + colIndex}
                className="bg-white max-w-full w-full xl:w-[500px] border border-border rounded-lg shadow-md transition-shadow duration-200 p-6"
              >
                <div className="space-y-5">
                  {isRefreshing ? (
                    <div className="w-full">
                      <div className="w-full">
                        <div className="h-4 w-24 bg-gray-200 rounded animate-pulse mb-2" />
                        <div className="h-10 w-full bg-gray-200 rounded animate-pulse" />
                      </div>

                      <div>
                        <div className="h-4 w-24 bg-gray-200 rounded animate-pulse mb-2" />
                        <div className="h-10 w-full bg-gray-200 rounded animate-pulse" />
                      </div>

                      <div>
                        <div className="h-4 w-24 bg-gray-200 rounded animate-pulse mb-2" />
                        <div className="h-24 w-full bg-gray-200 rounded animate-pulse" />
                      </div>
                    </div>
                  ) : (
                    <>
                      <div>
                        <div className="flex w-full items-center gap-x-1">
                          <Label
                            small
                            className="text-sm font-medium text-gray-700"
                          >
                            Name
                          </Label>
                          <TooltipProvider delayDuration={50}>
                            <Tooltip>
                              <TooltipTrigger>
                                <FiInfo size={12} />
                              </TooltipTrigger>
                              <TooltipContent side="top" align="center">
                                <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                                  Shows up as the &quot;title&quot; for this
                                  Starter Message. For example, &quot;Write an
                                  email.&quot;
                                </p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </div>
                        <Field
                          name={`starter_messages.${
                            rowIndex * 2 + colIndex
                          }.name`}
                          className="mt-1 w-full px-4 py-2.5 bg-background border border-border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition"
                          autoComplete="off"
                          placeholder="Enter a name..."
                          onChange={(e: any) => {
                            touchStarterMessages();
                            handleChange(e);
                          }}
                        />
                        <ErrorMessage
                          name={`starter_messages.${
                            rowIndex * 2 + colIndex
                          }.name`}
                          component="div"
                          className="text-red-500 text-sm mt-1"
                        />
                      </div>

                      <div>
                        <div className="flex w-full items-center gap-x-1">
                          <Label
                            small
                            className="text-sm font-medium text-gray-700"
                          >
                            Message
                          </Label>
                          <TooltipProvider delayDuration={50}>
                            <Tooltip>
                              <TooltipTrigger>
                                <FiInfo size={12} />
                              </TooltipTrigger>
                              <TooltipContent side="top" align="center">
                                <p className="bg-background-900 max-w-[200px] mb-1 text-sm rounded-lg p-1.5 text-white">
                                  The actual message to be sent as the initial
                                  user message.
                                </p>
                              </TooltipContent>
                            </Tooltip>
                          </TooltipProvider>
                        </div>
                        <Field
                          name={`starter_messages.${
                            rowIndex * 2 + colIndex
                          }.message`}
                          className="mt-1  text-sm  w-full px-4 py-2.5 bg-background border border-border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent transition min-h-[100px] resize-y"
                          as="textarea"
                          autoComplete="off"
                          placeholder="Enter the message..."
                          onChange={(e: any) => {
                            touchStarterMessages();
                            handleChange(e);
                          }}
                        />
                        <ErrorMessage
                          name={`starter_messages.${
                            rowIndex * 2 + colIndex
                          }.message`}
                          component="div"
                          className="text-red-500 text-sm mt-1"
                        />
                      </div>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>

          <button
            type="button"
            onClick={() => {
              arrayHelpers.remove(rowIndex * 2 + 1);
              arrayHelpers.remove(rowIndex * 2);
            }}
            className="p-1.5 bg-white border border-gray-200 rounded-full text-gray-400 hover:text-red-500 hover:border-red-200 transition-colors mt-2"
            aria-label="Delete row"
          >
            <FiTrash2 size={14} />
          </button>
        </div>
      ))}

      {canAddMore && (
        <button
          type="button"
          onClick={() => {
            arrayHelpers.push({
              name: "",
              message: "",
            });
            arrayHelpers.push({
              name: "",
              message: "",
            });
          }}
          className="self-start flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-lg text-gray-600 hover:bg-gray-50 hover:border-gray-300 transition-colors"
        >
          <FiPlus size={16} />
          <span>Add Row</span>
        </button>
      )}
    </div>
  );
}
