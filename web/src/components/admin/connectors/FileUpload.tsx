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
  const [dragActive, setDragActive] = useState(false);
  const { setFieldValue } = useFormikContext();

  return (
    <div>
      <Dropzone
        onDrop={(acceptedFiles) => {
          let filesToSet: File[] = [];
          if (multiple) {
            filesToSet = acceptedFiles;
          } else {
            const acceptedFile = acceptedFiles[0];
            if (acceptedFile !== undefined) {
              filesToSet = [acceptedFile];
            }
          }

          if (filesToSet !== undefined) {
            setSelectedFiles(filesToSet);
          }

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
                  `Drag and drop ${
                    multiple ? "some files" : "a file"
                  } here, or click to select ${multiple ? "files" : "a file"}`}
              </b>
            </div>
          </section>
        )}
      </Dropzone>

      {selectedFiles.length > 0 && (
        <div className="mt-4">
          <h2 className="text-sm font-bold">
            Selected File{multiple ? "s" : ""}
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
