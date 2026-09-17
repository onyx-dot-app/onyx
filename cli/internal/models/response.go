package models

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
)

type itemKey struct {
	ResponseID                    int
	MessageID, ToolCallID, PartID string
}
type responseEntry struct {
	Identity ItemIdentity
	Item     ResponseItem
}

// ResponseState applies complete items and deltas to one response stream.
type ResponseState struct {
	entries []responseEntry
	indices map[itemKey]int
}
type ItemChange struct {
	Identity ItemIdentity
	Before   *ResponseItem
	After    ResponseItem
}

func (s *ResponseState) Apply(event StreamEvent) (*ItemChange, error) {
	var identity *ItemIdentity
	var item ResponseItem
	var delta *ItemDelta
	switch e := event.(type) {
	case ItemUpdateEvent:
		identity = e.Identity
		item = e.Item
	case ItemDeltaEvent:
		identity = e.Identity
		delta = &e.Delta
	default:
		return nil, nil
	}
	if identity == nil {
		return nil, fmt.Errorf("content update has no identity")
	}
	key := itemKey{identity.ResponseID, identity.MessageID, identity.ToolCallID, identity.PartID}
	if s.indices == nil {
		s.indices = make(map[itemKey]int)
	}
	index, found := s.indices[key]
	var before *ResponseItem
	if found {
		previous := s.entries[index].Item
		before = &previous
	}
	if delta != nil {
		if !found {
			return nil, fmt.Errorf("delta has no item: %s", identity.MessageID)
		}
		item = *before
		switch delta.Kind {
		case DeltaText:
			if item.Kind != ItemText && item.Kind != ItemReasoning {
				return nil, fmt.Errorf("text delta targets %s", item.Kind)
			}
			item.Text += delta.Text
			item.Citations = append(append([]Citation(nil), item.Citations...), delta.Citations...)
		case DeltaToolOutput:
			if item.Kind != ItemTool {
				return nil, fmt.Errorf("tool output targets %s", item.Kind)
			}
			if delta.Output != nil {
				item.Output = *delta.Output
			}
			if len(delta.Metadata) > 0 && string(delta.Metadata) != "null" {
				item.Metadata = delta.Metadata
			}
		case DeltaToolArguments:
			if item.Kind != ItemTool {
				return nil, fmt.Errorf("tool arguments target %s", item.Kind)
			}
			args := make(map[string]json.RawMessage, len(item.Arguments))
			for name, value := range item.Arguments {
				args[name] = value
			}
			for name, fragment := range delta.Arguments {
				var previous string
				if raw, ok := args[name]; ok {
					if err := json.Unmarshal(raw, &previous); err != nil {
						return nil, fmt.Errorf("streamed argument %s is not text: %w", name, err)
					}
				}
				encoded, err := json.Marshal(previous + fragment)
				if err != nil {
					return nil, err
				}
				args[name] = encoded
			}
			item.Arguments = args
		default:
			return nil, fmt.Errorf("unknown item delta %q", delta.Kind)
		}
	}
	if item.Kind != ItemText && item.Kind != ItemReasoning && item.Kind != ItemTool {
		return nil, fmt.Errorf("unknown item kind %q", item.Kind)
	}
	entry := responseEntry{Identity: *identity, Item: item}
	if found {
		s.entries[index] = entry
	} else {
		s.indices[key] = len(s.entries)
		s.entries = append(s.entries, entry)
	}
	return &ItemChange{Identity: *identity, Before: before, After: item}, nil
}
func visibleText(identity ItemIdentity, item ResponseItem) bool {
	return item.Kind == ItemText && (identity.ParentRunID == "" || item.Purpose == PurposeReport)
}
func (s *ResponseState) Text() string {
	var text strings.Builder
	for _, entry := range s.entries {
		if visibleText(entry.Identity, entry.Item) {
			text.WriteString(entry.Item.Text)
		}
	}
	return text.String()
}
func (s *ResponseState) Citations() map[int]string {
	citations := make(map[int]string)
	for _, entry := range s.entries {
		if entry.Identity.ParentRunID != "" {
			continue
		}
		for _, c := range entry.Item.Citations {
			citations[c.CitationNumber] = c.DocumentID
		}
	}
	return citations
}

// TextDelta avoids printing authoritative complete items twice on an append-only terminal.
func (c ItemChange) TextDelta() string {
	if !visibleText(c.Identity, c.After) {
		return ""
	}
	if c.Before == nil {
		return c.After.Text
	}
	if strings.HasPrefix(c.After.Text, c.Before.Text) {
		return strings.TrimPrefix(c.After.Text, c.Before.Text)
	}
	// Plain stdout cannot retract text; separate an authoritative correction from partial output.
	if c.After.Text != "" {
		return "\n" + c.After.Text
	}
	return ""
}

type searchMetadata struct {
	Type          string      `json:"type"`
	Queries       []string    `json:"queries"`
	SearchDocs    []SearchDoc `json:"search_docs"`
	DisplayedDocs []SearchDoc `json:"displayed_docs"`
}

func (c ItemChange) Activity() ([]string, error) {
	if c.After.Kind == ItemTool {
		switch c.After.Name {
		case "think_tool", "generate_plan", "generate_report", "generate_answer":
			return nil, nil
		}
	}
	var lines []string
	if c.Before == nil {
		if c.After.Kind == ItemReasoning {
			lines = append(lines, "Thinking…")
		}
		if c.After.Kind == ItemTool {
			lines = append(lines, "Using "+c.After.Name+"…")
		}
	}
	if c.After.Kind != ItemTool || len(c.After.Metadata) == 0 || string(c.After.Metadata) == "null" {
		return lines, nil
	}
	var current searchMetadata
	if err := json.Unmarshal(c.After.Metadata, &current); err != nil {
		return nil, fmt.Errorf("invalid tool metadata: %w", err)
	}
	if current.Type != "search_result" {
		return lines, nil
	}
	var previous searchMetadata
	if c.Before != nil && len(c.Before.Metadata) > 0 {
		if err := json.Unmarshal(c.Before.Metadata, &previous); err != nil {
			return nil, fmt.Errorf("invalid previous tool metadata: %w", err)
		}
	}
	if !reflect.DeepEqual(previous.Queries, current.Queries) && len(current.Queries) > 0 {
		lines = append(lines, "Searching: "+strings.Join(current.Queries, ", "))
	}
	docs := current.SearchDocs
	if current.DisplayedDocs != nil {
		docs = current.DisplayedDocs
	}
	previousDocs := previous.SearchDocs
	if previous.DisplayedDocs != nil {
		previousDocs = previous.DisplayedDocs
	}
	if len(docs) > 0 && !reflect.DeepEqual(docs, previousDocs) {
		lines = append(lines, fmt.Sprintf("Found %d documents", len(docs)))
	}
	return lines, nil
}
