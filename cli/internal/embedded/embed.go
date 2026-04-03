// Package embedded holds files that are compiled into the onyx-cli binary.
package embedded

import _ "embed"

//go:embed SKILL.md
var SkillMD string
