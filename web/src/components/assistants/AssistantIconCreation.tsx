import { Persona } from "@/app/admin/assistants/interfaces";
import { buildImgUrl } from "@/app/chat/files/images/utils";
import { useEffect, useState } from "react";
import Dropzone from "react-dropzone";
import { usePopup } from "../admin/connectors/Popup";

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
                <p className="font-base text-sm text-text-800">
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
