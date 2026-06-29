package cmd

import (
	"encoding/base64"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"

	"github.com/onyx-dot-app/onyx/cli/internal/api"
	"github.com/onyx-dot-app/onyx/cli/internal/exitcodes"
	"github.com/onyx-dot-app/onyx/cli/internal/iostreams"
	"github.com/onyx-dot-app/onyx/cli/internal/models"
	"github.com/spf13/cobra"
)

var validImageShapes = map[string]bool{
	"square":    true,
	"portrait":  true,
	"landscape": true,
}

var imageExtToMime = map[string]string{
	".png":  "image/png",
	".jpg":  "image/jpeg",
	".jpeg": "image/jpeg",
	".gif":  "image/gif",
	".webp": "image/webp",
}

type imageOptions struct {
	prompt  string
	output  string
	shape   string
	quality string
	num     int
	inputs  []string // reference image paths (edit only)
}

func newImageCmd(ios *iostreams.IOStreams) *cobra.Command {
	cmd := &cobra.Command{
		Use:   "image",
		Short: "Generate or edit images with the configured image provider",
		Long: `Generate or edit raster images using the image-generation provider the
admin configured at /admin/configuration/image-generation (OpenAI, Gemini, or
Azure). No API key is needed locally — generation runs server-side.

If no provider is configured the command exits with a clear message; ask an
admin to set one up in the admin panel.`,
	}
	cmd.AddCommand(newImageGenerateCmd(ios))
	cmd.AddCommand(newImageEditCmd(ios))
	return cmd
}

func newImageGenerateCmd(ios *iostreams.IOStreams) *cobra.Command {
	opts := imageOptions{}
	cmd := &cobra.Command{
		Use:   "generate",
		Short: "Generate image(s) from a text prompt",
		Example: `  onyx-cli image generate -p "a red bicycle on a beach" -o bike.png
  onyx-cli image generate -p "app icon, flat style" --shape square -n 3 -o icon.png`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return runImageGeneration(cmd, ios, opts)
		},
	}
	addCommonImageFlags(cmd, &opts)
	return cmd
}

func newImageEditCmd(ios *iostreams.IOStreams) *cobra.Command {
	opts := imageOptions{}
	cmd := &cobra.Command{
		Use:   "edit",
		Short: "Edit or composite existing image(s) guided by a prompt",
		Example: `  onyx-cli image edit -i photo.png -p "replace the sky with a sunset" -o out.png
  onyx-cli image edit -i a.png -i b.png -p "combine these into one scene" -o merged.png`,
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(opts.inputs) == 0 {
				return exitcodes.New(exitcodes.BadRequest,
					"edit requires at least one --input-image")
			}
			return runImageGeneration(cmd, ios, opts)
		},
	}
	addCommonImageFlags(cmd, &opts)
	cmd.Flags().StringArrayVarP(&opts.inputs, "input-image", "i", nil,
		"Input image path (repeat to composite multiple); first is the primary edit source")
	return cmd
}

func addCommonImageFlags(cmd *cobra.Command, opts *imageOptions) {
	cmd.Flags().StringVarP(&opts.prompt, "prompt", "p", "", "Text prompt (required)")
	cmd.Flags().StringVarP(&opts.output, "output", "o", "output.png", "Output file path")
	cmd.Flags().StringVar(&opts.shape, "shape", "square", "Image shape: square, portrait, or landscape")
	cmd.Flags().StringVarP(&opts.quality, "quality", "q", "", "Render quality (provider-specific, e.g. low/medium/high/auto)")
	cmd.Flags().IntVarP(&opts.num, "num", "n", 1, "Number of images to generate")
}

func buildImageRequest(opts imageOptions, references []models.ImageReferencePayload) models.ImageGenerationRequest {
	return models.ImageGenerationRequest{
		Prompt:          opts.prompt,
		Shape:           opts.shape,
		N:               opts.num,
		Quality:         opts.quality,
		ReferenceImages: references,
	}
}

func runImageGeneration(cmd *cobra.Command, ios *iostreams.IOStreams, opts imageOptions) error {
	if strings.TrimSpace(opts.prompt) == "" {
		return exitcodes.New(exitcodes.BadRequest,
			"no prompt provided\n  Usage: onyx-cli image generate -p \"your prompt\"")
	}
	if !validImageShapes[opts.shape] {
		return exitcodes.Newf(exitcodes.BadRequest,
			"invalid --shape %q (expected square, portrait, or landscape)", opts.shape)
	}
	if opts.num < 1 {
		return exitcodes.New(exitcodes.BadRequest, "--num must be at least 1")
	}

	references, err := loadReferenceImages(opts.inputs)
	if err != nil {
		return err
	}

	_, client, err := requireClient()
	if err != nil {
		return err
	}

	req := buildImageRequest(opts, references)

	ctx, stop := signal.NotifyContext(cmd.Context(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	if ios.IsStdoutTTY {
		fmt.Fprintf(ios.ErrOut, "\033[2mGenerating...\033[0m\n")
	}

	resp, err := client.GenerateImage(ctx, req)
	if err != nil {
		return imageErrorToExit(err)
	}

	paths, err := writeGeneratedImages(resp.Images, opts.output)
	if err != nil {
		return err
	}
	for _, p := range paths {
		fmt.Fprintln(ios.Out, p)
	}
	return nil
}

func loadReferenceImages(paths []string) ([]models.ImageReferencePayload, error) {
	if len(paths) == 0 {
		return nil, nil
	}
	references := make([]models.ImageReferencePayload, 0, len(paths))
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			return nil, exitcodes.Newf(exitcodes.BadRequest,
				"could not read input image %q: %v", p, err)
		}
		mime := imageExtToMime[strings.ToLower(filepath.Ext(p))]
		if mime == "" {
			mime = "image/png"
		}
		references = append(references, models.ImageReferencePayload{
			DataBase64: base64.StdEncoding.EncodeToString(data),
			MimeType:   mime,
		})
	}
	return references, nil
}

func writeGeneratedImages(images []models.GeneratedImagePayload, output string) ([]string, error) {
	if len(images) == 0 {
		return nil, exitcodes.New(exitcodes.ServerError, "no images returned")
	}
	ext := filepath.Ext(output)
	base := strings.TrimSuffix(output, ext)
	if ext == "" {
		ext = ".png"
	}

	if dir := filepath.Dir(output); dir != "." {
		if err := os.MkdirAll(dir, 0o755); err != nil {
			return nil, exitcodes.Newf(exitcodes.General,
				"failed to create output directory %q: %v", dir, err)
		}
	}

	paths := make([]string, 0, len(images))
	for i, img := range images {
		data, err := base64.StdEncoding.DecodeString(img.DataBase64)
		if err != nil {
			return nil, exitcodes.Newf(exitcodes.ServerError,
				"failed to decode returned image: %v", err)
		}
		path := output
		if len(images) > 1 {
			path = fmt.Sprintf("%s_%d%s", base, i+1, ext)
		}
		f, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
		if err != nil {
			return nil, exitcodes.Newf(exitcodes.General,
				"failed to write %q: %v", path, err)
		}
		if _, err := f.Write(data); err != nil {
			_ = f.Close()
			return nil, exitcodes.Newf(exitcodes.General,
				"failed to write %q: %v", path, err)
		}
		if err := f.Close(); err != nil {
			return nil, exitcodes.Newf(exitcodes.General,
				"failed to write %q: %v", path, err)
		}
		paths = append(paths, path)
	}
	return paths, nil
}

func imageErrorToExit(err error) error {
	var apiErr *api.OnyxAPIError
	if errors.As(err, &apiErr) && apiErr.StatusCode == 404 {
		return exitcodes.New(exitcodes.NotAvailable,
			"no image generation provider is configured\n"+
				"  Ask an admin to configure one at /admin/configuration/image-generation")
	}
	return apiErrorToExit(err, "image generation failed")
}
