package response

// ModelListResponse represents the OpenAI models list response
type ModelListResponse struct {
	Object string      `json:"object"`
	Data   []ModelData `json:"data"`
}

// ModelData represents a single model in the list
type ModelData struct {
	ID      string `json:"id"`
	Object  string `json:"object"`
	Created int64  `json:"created"`
	OwnedBy string `json:"owned_by"`
}

// BuildModelListResponse creates an OpenAI-format model list response
func BuildModelListResponse(modelIDs []string, providerNames map[string]string) *ModelListResponse {
	data := make([]ModelData, 0, len(modelIDs))
	for _, id := range modelIDs {
		data = append(data, ModelData{
			ID:      id,
			Object:  "model",
			Created: 0,
			OwnedBy: providerNames[id],
		})
	}
	return &ModelListResponse{
		Object: "list",
		Data:   data,
	}
}
