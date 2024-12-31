import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  LightBackgroundColors,
  DarkBackgroundColors,
  Shortcut,
  StoredBackgroundColors,
} from "./interfaces";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PencilIcon, PlusIcon } from "lucide-react";

export const ShortCut = ({
  shortCut,
  onEdit,
  theme,
}: {
  shortCut: Shortcut;
  onEdit: (shortcut: Shortcut) => void;
  theme: string;
}) => {
  return (
    <div
      className="w-24 h-24 flex-none rounded-xl shadow-lg relative group transition-all duration-300 ease-in-out hover:scale-105"
      style={{
        backgroundColor:
          theme === "light"
            ? LightBackgroundColors[shortCut.backgroundColor]
            : DarkBackgroundColors[shortCut.backgroundColor],
      }}
    >
      <button
        onClick={(e) => {
          e.stopPropagation();
          onEdit(shortCut);
        }}
        className="absolute top-1 right-1 p-1 bg-white/20 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-200"
      >
        <PencilIcon className="w-3 h-3 text-white" />
      </button>
      <div
        onClick={() => window.open(shortCut.url, "_blank")}
        className="w-full h-full flex flex-col items-center justify-center cursor-pointer"
      >
        <h1
          className={`text-white w-full text-center  font-semibold text-sm truncate px-2 ${
            theme === "light" ? "text-black" : "text-white"
          }`}
        >
          {shortCut.name}
        </h1>
      </div>
    </div>
  );
};

export const AddShortCut = ({
  openShortCutModal,
}: {
  openShortCutModal: () => void;
}) => {
  return (
    <button
      onClick={openShortCutModal}
      className="w-24 h-24 flex-none rounded-xl bg-white/10 hover:bg-white/20 backdrop-blur-sm transition-all duration-300 ease-in-out flex flex-col items-center justify-center"
    >
      <PlusIcon className="w-8 h-8 text-white mb-2" />
      <h1 className="text-white text-xs font-medium">New Bookmark</h1>
    </button>
  );
};

export const NewShortCutModal = ({
  isOpen,
  onClose,
  onAdd,
  editingShortcut,
  onDelete,
  theme,
}: {
  theme: string;
  isOpen: boolean;
  onClose: () => void;
  onDelete: (shortcut: Shortcut) => void;
  onAdd: (shortcut: Shortcut) => void;
  editingShortcut?: Shortcut | null;
}) => {
  const [name, setName] = useState(editingShortcut?.name || "");
  const [url, setUrl] = useState(editingShortcut?.url || "");
  const [backgroundColor, setBackgroundColor] =
    useState<StoredBackgroundColors>(
      editingShortcut?.backgroundColor || StoredBackgroundColors.BLUE
    );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onAdd({ name, url, backgroundColor });
    onClose();
  };

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-[95%] sm:max-w-[425px] bg-neutral-900 border-none text-white">
        <DialogHeader>
          <DialogTitle>
            {editingShortcut ? "Edit Shortcut" : "Add New Shortcut"}
          </DialogTitle>
          <DialogDescription>
            {editingShortcut
              ? "Modify your existing shortcut."
              : "Create a new shortcut for quick access to your favorite websites."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="w-full space-y-6">
          <div className="space-y-4 w-full">
            <div className="flex flex-col space-y-2">
              <Label
                htmlFor="name"
                className="text-sm font-medium text-neutral-300"
              >
                Name
              </Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-neutral-800 border-neutral-700 text-white"
                placeholder="Enter shortcut name"
              />
            </div>
            <div className="flex flex-col space-y-2">
              <Label
                htmlFor="url"
                className="text-sm font-medium text-neutral-300"
              >
                URL
              </Label>
              <Input
                id="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                className="bg-neutral-800 border-neutral-700 text-white"
                placeholder="https://example.com"
              />
            </div>
            <div className="flex flex-col space-y-2">
              <Label
                htmlFor="color"
                className="text-sm font-medium text-neutral-300"
              >
                Color
              </Label>
              <Select
                onValueChange={(value: StoredBackgroundColors) =>
                  setBackgroundColor(value)
                }
              >
                <SelectTrigger className="bg-neutral-800 border-neutral-700 text-white">
                  <div className="flex items-center">
                    <div
                      className="w-4 h-4 rounded-full mr-2"
                      style={{ backgroundColor }}
                    ></div>
                    <SelectValue placeholder="Select a color" />
                  </div>
                </SelectTrigger>
                <SelectContent className="bg-neutral-900  border-neutral-700">
                  {Object.values(StoredBackgroundColors).map((color) => (
                    <SelectItem
                      key={color}
                      value={color}
                      className="text-white focus:bg-neutral-950 focus:text-neutral-100  cursor-pointer"
                    >
                      <div className="flex items-center">{color}</div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="bg-blue-600 hover:bg-blue-700 text-white"
            >
              {editingShortcut ? "Save Changes" : "Add Shortcut"}
            </Button>
            {editingShortcut && (
              <Button
                type="button"
                variant="destructive"
                onClick={() => onDelete(editingShortcut)}
              >
                Delete
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export const MaxShortcutsReachedModal = ({
  onClose,
}: {
  onClose: () => void;
}) => {
  return (
    <Dialog onOpenChange={onClose}>
      <DialogContent className="sm:max-w-[425px] bg-neutral-900 text-white">
        <DialogHeader>
          <DialogTitle className="text-2xl font-bold text-center">
            Maximum Shortcuts Reached
          </DialogTitle>
        </DialogHeader>
        <div className="py-4">
          <p className="text-center text-neutral-300">
            You&apos;ve reached the maximum limit of 8 shortcuts. To add a new
            shortcut, please remove an existing one.
          </p>
        </div>
        <DialogFooter>
          <Button
            onClick={onClose}
            className="w-full bg-blue-600 hover:bg-blue-700 text-white"
          >
            Got it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
};
