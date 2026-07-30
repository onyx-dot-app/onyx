package models

type ImageReferencePayload struct {
	DataBase64 string `json:"data_base64"`
	MimeType   string `json:"mime_type,omitempty"`
}

// ImageGenerationRequest is the body for POST /build/image-generation/generate.
type ImageGenerationRequest struct {
	Prompt          string                  `json:"prompt"`
	Shape           string                  `json:"shape,omitempty"`
	N               int                     `json:"n,omitempty"`
	Quality         string                  `json:"quality,omitempty"`
	ReferenceImages []ImageReferencePayload `json:"reference_images,omitempty"`
}

type GeneratedImagePayload struct {
	DataBase64    string `json:"data_base64"`
	MimeType      string `json:"mime_type"`
	RevisedPrompt string `json:"revised_prompt"`
}

type ImageGenerationResponse struct {
	Images []GeneratedImagePayload `json:"images"`
}
