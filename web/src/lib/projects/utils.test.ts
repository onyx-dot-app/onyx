import { ChatFileType } from "@/app/app/types";
import { fileDescriptorToProjectFile, resendFiles } from "@/lib/projects/utils";

test("a retry sends the sent files once, then other composer files", () => {
  const sent = {
    id: "store-1",
    type: ChatFileType.PLAIN_TEXT,
    name: "a.txt",
    user_file_id: "user-1",
  };
  const other = fileDescriptorToProjectFile({
    id: "store-2",
    type: ChatFileType.PLAIN_TEXT,
    name: "b.txt",
    user_file_id: "user-2",
  });

  const files = resendFiles({ files: [sent] }, [
    fileDescriptorToProjectFile(sent),
    other,
  ]);

  expect(files.map((file) => file.id)).toEqual(["user-1", "user-2"]);
});
