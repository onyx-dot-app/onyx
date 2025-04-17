import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
import { SubLabel } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
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
              message: i18n.t(k.ONLY_ONE_FILE_CAN_BE_UPLOADED),
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
              <b className="text-text-darker">
                {i18n.t(k.DRAG_AND_DROP_A_PNG_OR_JPG_F)}
              </b>
            </div>

            {tmpImageUrl && (
              <div className="mt-4 mb-8">
                <SubLabel>{i18n.t(k.UPLOADED_IMAGE)}</SubLabel>
                <img
                  alt="Uploaded Image"
                  src={tmpImageUrl}
                  className="mt-4 max-w-xs max-h-64"
                />
              </div>
            )}
          </section>
        )}
      </Dropzone>
    </>
  );
}
