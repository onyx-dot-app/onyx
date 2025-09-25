"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import { useFormikContext } from "formik";
import { FC, useState } from "react";
import React from "react";
import Dropzone from "react-dropzone";

interface FileUploadProps {
  selectedFiles: File[];
  setSelectedFiles: (files: File[]) => void;
  message?: string;
  name?: string;
  multiple?: boolean;
  accept?: string;
}

export const FileUpload: FC<FileUploadProps> = ({
  name,
  selectedFiles,
  setSelectedFiles,
  message,
  multiple = true,
  accept,
}) => {
  const { t } = useTranslation();
  const [dragActive, setDragActive] = useState(false);
  const { setFieldValue } = useFormikContext();

  return (
    <div>
      <Dropzone
        onDrop={(acceptedFiles) => {
          const filesToSet = multiple ? acceptedFiles : [acceptedFiles[0]];
          setSelectedFiles(filesToSet);
          setDragActive(false);
          if (name) {
            setFieldValue(name, multiple ? filesToSet : filesToSet[0]);
          }
        }}
        onDragLeave={() => setDragActive(false)}
        onDragEnter={() => setDragActive(true)}
        multiple={multiple}
        accept={accept ? { [accept]: [] } : undefined}
      >
        {({ getRootProps, getInputProps }) => (
          <section>
            <div
              {...getRootProps()}
              className={
                "flex flex-col items-center w-full px-4 py-12 rounded " +
                "shadow-lg tracking-wide border border-border cursor-pointer" +
                (dragActive ? " border-accent" : "")
              }
            >
              <input {...getInputProps()} />
              <b className="text-text-darker">
                {message ||
                  `${t(k.DRAG_AND_DROP)} ${
                    multiple ? t(k.SOME_FILES) : t(k.A_FILE)
                  } ${t(k.HERE_OR_CLICK_TO_SELECT)} ${
                    multiple ? t(k.FILES) : t(k.A_FILE)
                  }`}
              </b>
            </div>
          </section>
        )}
      </Dropzone>

      {selectedFiles.length > 0 && (
        <div className="mt-4">
          <h2 className="text-sm font-bold">
            {t(k.SELECTED_FILE)}
            {multiple ? t(k.S) : ""}
          </h2>
          <ul>
            {selectedFiles.map((file) => (
              <div key={file.name} className="flex">
                <p className="text-sm mr-2">{file.name}</p>
              </div>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};
