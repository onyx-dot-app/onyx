// Package deployfiles provides the deployment files onyx-cli ships for the
// guided docker compose install, embedded into the binary.
//
// The copies under embedded/ are synced from deployment/ in the onyx repo by
// `ods generate-compose --write` (tools/ods); TestEmbeddedFilesMatchSource
// fails when they drift.
package deployfiles

import (
	"embed"
	"io/fs"
)

//go:embed embedded
var embeddedFS embed.FS

// File describes one managed deployment file.
type File struct {
	// EmbedPath is the file's path inside the embedded FS.
	EmbedPath string
	// RepoPath is the file's path in the onyx repo, used when fetching the
	// version matching a pinned release tag from raw.githubusercontent.com.
	RepoPath string
	// DestRel is the file's destination relative to the install root, using
	// slash separators.
	DestRel string
	// Mode is the permission bits applied when writing the file to disk
	// (embed.FS does not preserve them).
	Mode fs.FileMode
}

// Content returns the embedded copy of the file.
func (f File) Content() ([]byte, error) {
	return embeddedFS.ReadFile(f.EmbedPath)
}

// The managed files. DestRel mirrors the layout install.sh creates: compose
// files and .env under deployment/, nginx config under data/nginx/ (the
// compose file bind-mounts ../data/nginx), README at the root.
var (
	Compose = File{
		EmbedPath: "embedded/docker_compose/docker-compose.yml",
		RepoPath:  "deployment/docker_compose/docker-compose.yml",
		DestRel:   "deployment/docker-compose.yml",
		Mode:      0644,
	}
	LiteOverlay = File{
		EmbedPath: "embedded/docker_compose/docker-compose.onyx-lite.yml",
		RepoPath:  "deployment/docker_compose/docker-compose.onyx-lite.yml",
		DestRel:   "deployment/docker-compose.onyx-lite.yml",
		Mode:      0644,
	}
	CraftOverlay = File{
		EmbedPath: "embedded/docker_compose/docker-compose.craft.yml",
		RepoPath:  "deployment/docker_compose/docker-compose.craft.yml",
		DestRel:   "deployment/docker-compose.craft.yml",
		Mode:      0644,
	}
	// DevOverlay publishes the service ports (API, Postgres, Redis,
	// OpenSearch, model server, MinIO, code interpreter) on the host. Stacked
	// on Compose like LiteOverlay, but flag-only (--dev): it takes the
	// deployment's internals out from behind nginx.
	DevOverlay = File{
		EmbedPath: "embedded/docker_compose/docker-compose.dev.yml",
		RepoPath:  "deployment/docker_compose/docker-compose.dev.yml",
		DestRel:   "deployment/docker-compose.dev.yml",
		Mode:      0644,
	}
	// ProdCompose is the standalone production compose file: run on its own
	// (not stacked on Compose), it is the complete prod stack with TLS.
	ProdCompose = File{
		EmbedPath: "embedded/docker_compose/docker-compose.prod.yml",
		RepoPath:  "deployment/docker_compose/docker-compose.prod.yml",
		DestRel:   "deployment/docker-compose.prod.yml",
		Mode:      0644,
	}
	EnvTemplate = File{
		EmbedPath: "embedded/docker_compose/env.template",
		RepoPath:  "deployment/docker_compose/env.template",
		DestRel:   "deployment/env.template",
		Mode:      0644,
	}
	EnvProdTemplate = File{
		EmbedPath: "embedded/docker_compose/env.prod.template",
		RepoPath:  "deployment/docker_compose/env.prod.template",
		DestRel:   "deployment/env.prod.template",
		Mode:      0644,
	}
	EnvNginxTemplate = File{
		EmbedPath: "embedded/docker_compose/env.nginx.template",
		RepoPath:  "deployment/docker_compose/env.nginx.template",
		DestRel:   "deployment/env.nginx.template",
		Mode:      0644,
	}
	Readme = File{
		EmbedPath: "embedded/docker_compose/README.md",
		RepoPath:  "deployment/docker_compose/README.md",
		DestRel:   "README.md",
		Mode:      0644,
	}
	NginxAppConf = File{
		EmbedPath: "embedded/data/nginx/app.conf.template",
		RepoPath:  "deployment/data/nginx/app.conf.template",
		DestRel:   "data/nginx/app.conf.template",
		Mode:      0644,
	}
	NginxAppConfProd = File{
		EmbedPath: "embedded/data/nginx/app.conf.template.prod",
		RepoPath:  "deployment/data/nginx/app.conf.template.prod",
		DestRel:   "data/nginx/app.conf.template.prod",
		Mode:      0644,
	}
	NginxRunScript = File{
		EmbedPath: "embedded/data/nginx/run-nginx.sh",
		RepoPath:  "deployment/data/nginx/run-nginx.sh",
		DestRel:   "data/nginx/run-nginx.sh",
		Mode:      0755,
	}
)

// OverrideNames lists the user-owned compose override, in the precedence
// order Docker Compose's own auto-discovery uses (compose-go's
// DefaultOverrideFileNames — first match wins). None of these is a File: the
// CLI never writes, fetches, checksums, or backs any of them up — it only
// stacks whichever one is found last on the -f list when the deployment
// directory has one. The CLI's explicit -f flags otherwise suppress Compose's
// own auto-discovery of these same names.
var OverrideNames = []string{
	"compose.override.yml",
	"compose.override.yaml",
	"docker-compose.override.yml",
	"docker-compose.override.yaml",
}

// All lists every managed file.
var All = []File{
	Compose,
	LiteOverlay,
	CraftOverlay,
	DevOverlay,
	ProdCompose,
	EnvTemplate,
	EnvProdTemplate,
	EnvNginxTemplate,
	Readme,
	NginxAppConf,
	NginxAppConfProd,
	NginxRunScript,
}
