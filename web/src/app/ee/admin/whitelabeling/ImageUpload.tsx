import { Persona } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/files/images/utils";
import { SubLabel } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Text } from "@tremor/react";
import { useEffect, useState } from "react";
import Dropzone from "react-dropzone";

export function ImageUpload({
  selectedFile,
  setSelectedFile,
}: {
  selectedFile: File | null;
  setSelectedFile: (file: File) => void;
}) {
  const [tmpImageUrl, setTmpImageUrl] = useState<string>("");

  useEffect(() => {
    if (selectedFile) {
      setTmpImageUrl(URL.createObjectURL(selectedFile));
    } else {
      setTmpImageUrl("");
    }
  }, [selectedFile]);

  const [dragActive, setDragActive] = useState(false);
  const { popup, setPopup } = usePopup();

  return (
    <>
      {popup}
      <Dropzone
        onDrop={(acceptedFiles) => {
          if (acceptedFiles.length !== 1) {
            setPopup({
              type: "error",
              message: "Only one file can be uploaded at a time",
            });
          }

          setTmpImageUrl(URL.createObjectURL(acceptedFiles[0]));
          setSelectedFile(acceptedFiles[0]);
          setDragActive(false);
        }}
        onDragLeave={() => setDragActive(false)}
        onDragEnter={() => setDragActive(true)}
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
              <b className="text-emphasis">
                Drag and drop a .png or .jpg file, or click to select a file!
              </b>
            </div>

            {tmpImageUrl && (
              <div className="mt-4 mb-8">
                <SubLabel>Uploaded Image:</SubLabel>
                <img src={tmpImageUrl} className="mt-4 max-w-xs max-h-64" />
              </div>
            )}
          </section>
        )}
      </Dropzone>
    </>
  );
}

export const IconImageSelection = ({
  existingPersona,
  setFieldValue,
}: {
  existingPersona: Persona | null;
  setFieldValue: (
    field: string,
    value: any,
    shouldValidate?: boolean
  ) => Promise<any>;
}) => {
  const [uploadedImage, setUploadedImage] = useState<File | null>(null);

  const updateFile = (image: File | null) => {
    setUploadedImage(image);
    setFieldValue("uploaded_image", image);
  };

  return (
    <div className="mt-2 gap-y-2 flex flex-col">
      <p className="font-bold text-sm text-gray-800">Or Upload Image</p>
      {existingPersona && existingPersona.uploaded_image_id && (
        <div className="flex gap-x-2">
          Current image:
          <img
            className="h-12 w-12"
            src={buildImgUrl(existingPersona?.uploaded_image_id)}
          />
        </div>
      )}
      <IconImageUpload selectedFile={uploadedImage} updateFile={updateFile} />
      <p className="text-sm text-gray-600">
        Uploading an image will override the generated icon.
      </p>
    </div>
  );
};
export function IconImageUpload({
  selectedFile,
  updateFile,
}: {
  selectedFile: File | null;
  updateFile: (image: File | null) => void;
}) {
  const [tmpImageUrl, setTmpImageUrl] = useState<string>("");

  useEffect(() => {
    if (selectedFile) {
      setTmpImageUrl(URL.createObjectURL(selectedFile));
    } else {
      setTmpImageUrl("");
    }
  }, [selectedFile]);

  const [dragActive, setDragActive] = useState(false);
  const { popup, setPopup } = usePopup();

  return (
    <>
      {popup}

      <Dropzone
        onDrop={(acceptedFiles) => {
          if (acceptedFiles.length !== 1) {
            setPopup({
              type: "error",
              message: "Only one file can be uploaded at a time",
            });
          }
          setTmpImageUrl(URL.createObjectURL(acceptedFiles[0]));
          updateFile(acceptedFiles[0]);
          setDragActive(false);
        }}
        onDragLeave={() => setDragActive(false)}
        onDragEnter={() => setDragActive(true)}
      >
        {({ getRootProps, getInputProps }) => (
          <section>
            {!selectedFile && (
              <div
                {...getRootProps()}
                className={
                  "flex flex-col items-center max-w-[200px] p-2 rounded " +
                  "shadow-lg border border-border cursor-pointer" +
                  (dragActive ? " border-accent" : "")
                }
              >
                <input {...getInputProps()} />
                <p className="font-base text-sm text-neutral-800">
                  Upload a .png or .jpg file
                </p>
              </div>
            )}
            {tmpImageUrl && (
              <div className="flex mt-2 gap-x-2">
                Uploaded Image:
                <img src={tmpImageUrl} className="h-12 w-12"></img>
              </div>
            )}
            {selectedFile && (
              <button
                onClick={() => {
                  updateFile(null);
                  setTmpImageUrl("");
                }}
              >
                Reset
              </button>
            )}
          </section>
        )}
      </Dropzone>
    </>
  );
}
