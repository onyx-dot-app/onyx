import React, { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Campaign } from "@/lib/marketing/types";
import { generateTextContent, generateImageContent } from "@/services/openaiService";
import { Loader2 } from "lucide-react";

interface ContentGenerationModalProps {
  campaign: Campaign;
  onContentGenerated: (id: string, content: string, type: 'text' | 'image') => void;
  trigger: React.ReactNode;
  open: boolean;
  setOpen: (open: boolean) => void;
}

export default function ContentGenerationModal({
  campaign,
  onContentGenerated,
  trigger,
  open,
  setOpen,
}: ContentGenerationModalProps) {
  const [prompt, setPrompt] = useState("");
  const [contentType, setContentType] = useState<"text" | "image">("text");
  const [generatedContent, setGeneratedContent] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState("");

  const handleGenerate = async () => {
    if (!prompt.trim()) return;

    setIsGenerating(true);
    setError("");
    setGeneratedContent("");

    try {
      let content: string;
      if (contentType === "text") {
        content = await generateTextContent(prompt);
      } else {
        content = await generateImageContent(prompt);
      }
      setGeneratedContent(content);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to generate content");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleSaveContent = () => {
    if (generatedContent) {
      onContentGenerated(campaign.id, generatedContent, contentType);
      setPrompt("");
      setGeneratedContent("");
      setError("");
      setOpen(false);
    }
  };

  const handleClose = () => {
    setPrompt("");
    setGeneratedContent("");
    setError("");
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className="max-w-[95%] sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Generate AI Content for "{campaign.name}"</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col space-y-4 w-full">
          <div className="space-y-2 w-full">
            <Label htmlFor="contentType">Content Type</Label>
            <Select value={contentType} onValueChange={(value: any) => setContentType(value)}>
              <SelectTrigger className="w-full">
                <SelectValue placeholder="Select content type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="text">Text Content</SelectItem>
                <SelectItem value="image">Image Content</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2 w-full">
            <Label htmlFor="prompt">Prompt</Label>
            <Textarea
              id="prompt"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder={
                contentType === "text"
                  ? "Describe the marketing text you want to generate..."
                  : "Describe the image you want to generate..."
              }
              rows={3}
              className="w-full focus-visible:border focus-visible:border-neutral-200 focus-visible:ring-0 !focus:ring-offset-0 !focus:ring-0 !focus:border-0 !focus:ring-transparent !focus:outline-none"
            />
          </div>

          <Button
            onClick={handleGenerate}
            disabled={!prompt.trim() || isGenerating}
            className="w-full"
          >
            {isGenerating ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Generating...
              </>
            ) : (
              `Generate ${contentType === "text" ? "Text" : "Image"}`
            )}
          </Button>

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 rounded-md">
              <p className="text-sm text-red-600">{error}</p>
            </div>
          )}

          {generatedContent && (
            <div className="space-y-3">
              <Label>Generated Content:</Label>
              <div className="p-4 bg-gray-50 border border-gray-200 rounded-md">
                {contentType === "text" ? (
                  <div className="whitespace-pre-wrap text-sm">{generatedContent}</div>
                ) : (
                  <img
                    src={generatedContent}
                    alt="Generated content"
                    className="max-w-full h-auto rounded-md"
                  />
                )}
              </div>
              <Button onClick={handleSaveContent} className="w-full">
                Save to Campaign
              </Button>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
