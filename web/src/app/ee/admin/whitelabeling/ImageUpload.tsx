import { SubLabel } from "@/components/Field";
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
              message: "Only one file can be uploaded at a time",
            });
            return;
          }

          const acceptedFile = acceptedFiles[0];
          if (acceptedFile === undefined) {
            setPopup({
              type: "error",
              message: "acceptedFile cannot be undefined",
            });
            return;
          }

          setTmpImageUrl(URL.createObjectURL(acceptedFile));
          setSelectedFile(acceptedFile);
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
                Drag and drop a .png or .jpg file, or click to select a file!
              </b>
            </div>

            {tmpImageUrl && (
              <div className="mt-4 mb-8">
                <SubLabel>Uploaded Image:</SubLabel>
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
