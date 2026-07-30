#!/bin/bash

# Onyx installer — a bootstrap for `onyx-cli deploy install`.
#
# The guided install itself lives in the Onyx CLI (Go). This script only
# installs that CLI and hands over; every argument is forwarded untouched.
#
#   curl -fsSL https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.sh | bash
#   curl -fsSL https://raw.githubusercontent.com/onyx-dot-app/onyx/main/deployment/docker_compose/install.sh | bash -s -- --lite --no-prompt
#
# Environment:
#   ONYX_CLI_VERSION  onyx-cli release to install (e.g. v1.3.1). Defaults to
#                     the newest published release.
#   ONYX_CLI_BIN_DIR  where the binary is installed. Defaults to
#                     /usr/local/bin when running as root, else ~/.local/bin.
#   ONYX_CLI_NO_MODIFY_PATH
#                     set to skip adding ~/.local/bin to PATH in the shell
#                     startup files.
#
# This script must remain compatible with bash 3.2 — macOS still ships
# 3.2.57 by default and the curl-pipe installer is invoked with /bin/bash.
# Avoid bash 4+ features (associative arrays, ${var,,}, etc.).
set -eo pipefail

REPO="onyx-dot-app/onyx"
RELEASES_URL="https://github.com/${REPO}/releases"
# Rolling release that always carries the newest CLI under version-less asset
# names. The repo-global releases/latest alias can't be used: it resolves to
# the Onyx app releases, not the CLI ones.
LATEST_TAG="cli-latest"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1" >&2
}

print_info() {
    echo -e "${YELLOW}ℹ${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC}  $1"
}

show_help() {
    echo "Onyx Installation Script"
    echo ""
    echo "Installs the Onyx CLI and runs its guided deployment:"
    echo "  onyx-cli deploy install [OPTIONS]"
    echo ""
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Common options (forwarded to the CLI):"
    echo "  --lite           Deploy Onyx Lite (no OpenSearch, Redis, or model servers)"
    echo "  --include-craft  Enable Onyx Craft (AI-powered web app building)"
    echo "  --tag <tag>      Image tag to deploy (default: the latest Onyx release)"
    echo "  --local          Use existing config files instead of downloading them"
    echo "  --no-prompt      Run non-interactively with defaults (for CI/automation)"
    echo "  --dry-run        Show what would be done without making changes"
    echo "  --verbose        Show detailed output for debugging"
    echo "  --no-wait        Return as soon as containers are started"
    echo "  --dir <path>     Deployment directory (default: ~/.config/onyx, or an"
    echo "                   existing ./onyx_data)"
    echo "  --help, -h       Show this help message"
    echo ""
    echo "Run 'onyx-cli deploy install --help' for the full list."
    echo ""
    echo "Managing an existing deployment (these replace the retired"
    echo "--shutdown / --delete-data flags):"
    echo "  onyx-cli deploy status     Versions, containers, and health"
    echo "  onyx-cli deploy logs       Logs of the deployment's containers"
    echo "  onyx-cli deploy stop       Stop the containers, keep the data"
    echo "  onyx-cli deploy upgrade    Upgrade to a newer version"
    echo "  onyx-cli deploy uninstall  Remove the deployment and all its data"
    echo ""
    echo "Environment:"
    echo "  ONYX_CLI_VERSION  onyx-cli release to install (default: newest)"
    echo "  ONYX_CLI_BIN_DIR  install location (default: ~/.local/bin, or"
    echo "                    /usr/local/bin as root)"
    echo "  ONYX_CLI_NO_MODIFY_PATH"
    echo "                    don't touch shell startup files to add ~/.local/bin"
    echo "                    to PATH"
}

for arg in "$@"; do
    case "$arg" in
        --help|-h)
            show_help
            exit 0
            ;;
    esac
done

# --- Downloader detection (curl with wget fallback) ---
DOWNLOADER=""
if command -v curl &> /dev/null; then
    DOWNLOADER="curl"
elif command -v wget &> /dev/null; then
    DOWNLOADER="wget"
else
    print_error "Neither curl nor wget found. Please install one and retry."
    exit 1
fi

download_file() {
    local url="$1"
    local output="$2"
    if [[ "$DOWNLOADER" == "curl" ]]; then
        curl -fsSL --retry 3 --retry-delay 2 --retry-connrefused -o "$output" "$url"
    else
        wget -q --tries=3 --timeout=20 -O "$output" "$url"
    fi
}

# --- Platform detection ---
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Linux)
        OS="linux"
        ;;
    Darwin)
        OS="darwin"
        ;;
    MINGW*|MSYS*|CYGWIN*|Windows_NT)
        print_error "This script does not support Windows shells."
        echo "  Use the PowerShell installer instead:" >&2
        echo "    irm https://raw.githubusercontent.com/${REPO}/main/deployment/docker_compose/install.ps1 | iex" >&2
        exit 1
        ;;
    *)
        print_error "Unsupported operating system: ${OS}"
        echo "  Onyx supports Linux and macOS. See https://docs.onyx.app/deployment/overview" >&2
        exit 1
        ;;
esac

case "$ARCH" in
    x86_64|amd64)
        ARCH="amd64"
        ;;
    aarch64|arm64)
        ARCH="arm64"
        ;;
    *)
        print_error "Unsupported architecture: ${ARCH}"
        echo "  Prebuilt onyx-cli binaries exist for amd64 and arm64 only." >&2
        echo "  Install from source or PyPI instead: pip install onyx-cli" >&2
        exit 1
        ;;
esac

# --- Resolve the release to download ---
# Pinned versions live under their own cli/vX.Y.Z tag with versioned asset
# names; the default rolling release drops the version from both.
if [[ -n "$ONYX_CLI_VERSION" ]]; then
    CLI_VERSION="${ONYX_CLI_VERSION#v}"
    ARCHIVE_NAME="onyx-cli_${CLI_VERSION}_${OS}_${ARCH}.tar.gz"
    CHECKSUMS_NAME="onyx-cli_${CLI_VERSION}_checksums.txt"
    DOWNLOAD_BASE="${RELEASES_URL}/download/cli/v${CLI_VERSION}"
    VERSION_LABEL="v${CLI_VERSION}"
else
    ARCHIVE_NAME="onyx-cli_${OS}_${ARCH}.tar.gz"
    CHECKSUMS_NAME="onyx-cli_checksums.txt"
    DOWNLOAD_BASE="${RELEASES_URL}/download/${LATEST_TAG}"
    VERSION_LABEL="latest"
fi

# --- Resolve where the binary goes ---
DEFAULT_USER_BIN_DIR=""
if [[ -n "$ONYX_CLI_BIN_DIR" ]]; then
    BIN_DIR="$ONYX_CLI_BIN_DIR"
elif [[ "$(id -u)" -eq 0 ]]; then
    BIN_DIR="/usr/local/bin"
else
    BIN_DIR="${HOME}/.local/bin"
    DEFAULT_USER_BIN_DIR="yes"
fi
BIN_PATH="${BIN_DIR}/onyx-cli"

TMP_DIR=""
cleanup() {
    if [[ -n "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
        TMP_DIR=""
    fi
}
trap cleanup EXIT

TMP_DIR="$(mktemp -d)"

print_info "Installing onyx-cli (${VERSION_LABEL}, ${OS}/${ARCH})..."

if ! download_file "${DOWNLOAD_BASE}/${ARCHIVE_NAME}" "${TMP_DIR}/${ARCHIVE_NAME}"; then
    print_error "Failed to download ${ARCHIVE_NAME}"
    if [[ -n "$ONYX_CLI_VERSION" ]]; then
        echo "  Check that ${VERSION_LABEL} exists: ${RELEASES_URL}?q=cli%2Fv" >&2
    else
        echo "  Please ensure you have internet connection and try again." >&2
    fi
    exit 1
fi

# --- Verify the download ---
# The checksums file covers every asset in the release; the archive's own line
# is the one that matters. Every failure here is fatal: the archive is about to
# be executed, so an unverified one is never installed.
verify_checksum() {
    local archive="${TMP_DIR}/${ARCHIVE_NAME}"
    local sums="${TMP_DIR}/${CHECKSUMS_NAME}"
    local expected actual

    if ! download_file "${DOWNLOAD_BASE}/${CHECKSUMS_NAME}" "$sums"; then
        print_error "Failed to download ${CHECKSUMS_NAME}"
        echo "  The downloaded binary cannot be verified, so it will not be installed." >&2
        echo "  Check your internet connection and try again." >&2
        return 1
    fi

    expected="$(awk -v name="$ARCHIVE_NAME" '$2 == name { print $1; exit }' "$sums")"
    if [[ -z "$expected" ]]; then
        print_error "No checksum listed for ${ARCHIVE_NAME} in ${CHECKSUMS_NAME}"
        echo "  The downloaded binary cannot be verified, so it will not be installed." >&2
        echo "  Please report this at ${RELEASES_URL%/releases}/issues" >&2
        return 1
    fi

    if command -v sha256sum &> /dev/null; then
        actual="$(sha256sum "$archive" | awk '{print $1}')"
    elif command -v shasum &> /dev/null; then
        actual="$(shasum -a 256 "$archive" | awk '{print $1}')"
    elif command -v openssl &> /dev/null; then
        actual="$(openssl dgst -sha256 "$archive" | awk '{print $NF}')"
    else
        print_error "No sha256 tool found (sha256sum, shasum, or openssl)"
        echo "  The downloaded binary cannot be verified, so it will not be installed." >&2
        echo "  Install one of those tools and try again." >&2
        return 1
    fi

    if [[ "$actual" != "$expected" ]]; then
        print_error "Checksum mismatch for ${ARCHIVE_NAME}"
        echo "  expected: ${expected}" >&2
        echo "  actual:   ${actual}" >&2
        return 1
    fi
    return 0
}

verify_checksum || exit 1

if ! tar -xzf "${TMP_DIR}/${ARCHIVE_NAME}" -C "$TMP_DIR" onyx-cli; then
    print_error "Failed to extract ${ARCHIVE_NAME}"
    exit 1
fi

if ! mkdir -p "$BIN_DIR" 2>/dev/null || [[ ! -w "$BIN_DIR" ]]; then
    print_error "Cannot write to ${BIN_DIR}"
    echo "  Re-run with sudo, or set ONYX_CLI_BIN_DIR to a writable directory." >&2
    exit 1
fi

chmod +x "${TMP_DIR}/onyx-cli"
mv -f "${TMP_DIR}/onyx-cli" "$BIN_PATH"
print_success "onyx-cli installed to ${BIN_PATH}"

# --- Make onyx-cli reachable by name ---
# The install below runs through $BIN_PATH either way, but the deployment is
# managed afterwards with `onyx-cli deploy status|logs|upgrade|uninstall`, so a
# PATH that doesn't cover BIN_DIR turns every one of those into "command not
# found". ~/.local/bin is not on PATH by default on macOS, and Debian's
# ~/.profile only adds it if the directory already existed at login — which it
# may not have until this script created it moments ago.
PATH_MARKER="# Added by the Onyx installer"

# Appends `line` to `profile` under PATH_MARKER unless the marker is already
# there. Returns non-zero when the file cannot be written so the caller can
# fall back to printing manual instructions.
append_line_to_profile() {
    local profile="$1"
    local line="$2"
    if [[ -f "$profile" ]] && grep -Fq "$PATH_MARKER" "$profile" 2>/dev/null; then
        return 0
    fi
    mkdir -p "$(dirname "$profile")" 2>/dev/null || return 1
    # 2>/dev/null must precede >>: redirections apply left to right, and a
    # failing append would otherwise print the shell's error before stderr
    # is silenced.
    printf '\n%s\n%s\n' "$PATH_MARKER" "$line" 2>/dev/null >> "$profile"
}

case ":${PATH}:" in
    *":${BIN_DIR}:"*)
        # An onyx-cli earlier in PATH (e.g. a pip install) would shadow the one
        # just installed, leaving the follow-up `onyx-cli deploy` commands on a
        # different version than the install ran with.
        SHADOWED_BY="$(command -v onyx-cli 2>/dev/null || true)"
        if [[ -n "$SHADOWED_BY" ]] && [[ "$SHADOWED_BY" != "$BIN_PATH" ]]; then
            print_warning "Another onyx-cli takes precedence in PATH: ${SHADOWED_BY}"
        fi
        ;;
    *)
        # Persist BIN_DIR into the login shell's profile so onyx-cli still
        # resolves in new shells once this installer hands over to the CLI.
        # The script itself runs under bash even when the user's shell is zsh
        # or fish, hence the $SHELL sniffing. Only the default user-local
        # location is patched in: an explicit ONYX_CLI_BIN_DIR means the
        # caller manages their own PATH, and ONYX_CLI_NO_MODIFY_PATH opts out.
        PROFILE_FILE=""
        PATH_LINE=""
        if [[ -n "$DEFAULT_USER_BIN_DIR" ]] && [[ -z "$ONYX_CLI_NO_MODIFY_PATH" ]]; then
            # The startup files get the unexpanded $HOME so they stay portable.
            # shellcheck disable=SC2016
            PATH_LINE='export PATH="$HOME/.local/bin:$PATH"'
            case "${SHELL##*/}" in
                zsh)
                    PROFILE_FILE="${ZDOTDIR:-$HOME}/.zshrc"
                    ;;
                bash)
                    # macOS terminals start login shells, which skip ~/.bashrc.
                    if [[ "$OS" == "darwin" ]]; then
                        PROFILE_FILE="${HOME}/.bash_profile"
                    else
                        PROFILE_FILE="${HOME}/.bashrc"
                    fi
                    ;;
                fish)
                    PROFILE_FILE="${HOME}/.config/fish/config.fish"
                    # shellcheck disable=SC2016
                    PATH_LINE='fish_add_path "$HOME/.local/bin"'
                    ;;
            esac
        fi

        if [[ -n "$PROFILE_FILE" ]] && append_line_to_profile "$PROFILE_FILE" "$PATH_LINE"; then
            print_success "Added ${BIN_DIR} to PATH in ${PROFILE_FILE}"
            print_info "Restart your shell (or run the line below) to pick it up:"
            echo -e "   ${BOLD}${PATH_LINE}${NC}"
        else
            print_warning "${BIN_DIR} is not in your PATH — add it to run onyx-cli directly:"
            echo -e "   ${BOLD}export PATH=\"${BIN_DIR}:\$PATH\"${NC}"
        fi
        # Fix up this process too so anything the CLI spawns can find it.
        export PATH="${BIN_DIR}:${PATH}"
        ;;
esac

# The temp dir is gone by the time exec replaces this process, so drop it now:
# an EXIT trap never fires across exec.
cleanup

# `curl ... | bash` leaves stdin on the pipe, and the CLI only prompts when
# stdin is a terminal. Reconnect it to the controlling terminal (when there is
# one) so a piped install is still interactive, the way this script's previous
# implementation read its own prompts from /dev/tty.
if [[ ! -t 0 ]] && (: < /dev/tty) 2> /dev/null; then
    exec "$BIN_PATH" deploy install "$@" < /dev/tty
fi

exec "$BIN_PATH" deploy install "$@"
