/**
 * Utility functions for parsing and validating GitHub URLs and repository information
 */

export interface ParsedGithubRepo {
  owner: string;
  repo: string;
}

export interface ParseError {
  error: string;
}

/**
 * Parse a GitHub URL or owner/repo string into structured components
 *
 * Supports formats:
 * - https://github.com/owner/repo
 * - http://github.com/owner/repo (upgraded to https)
 * - github.com/owner/repo
 * - www.github.com/owner/repo
 * - owner/repo
 * - owner (just the owner, no repo)
 *
 * @param input - GitHub URL or owner/repo string
 * @returns ParsedGithubRepo object with owner and repo, or ParseError if invalid
 */
export function parseGithubUrl(input: string): ParsedGithubRepo | ParseError {
  if (!input || typeof input !== "string") {
    return { error: "Input is required" };
  }

  // Trim whitespace
  const trimmed = input.trim();

  if (!trimmed) {
    return { error: "Input cannot be empty" };
  }

  // Remove trailing slashes
  const cleaned = trimmed.replace(/\/+$/, "");

  // Try to parse as URL
  try {
    // Add protocol if missing for URL parsing
    let urlString = cleaned;
    if (!cleaned.startsWith("http://") && !cleaned.startsWith("https://")) {
      // Check if it looks like a URL (contains github.com)
      if (cleaned.includes("github.com")) {
        urlString = "https://" + cleaned;
      }
    }

    const url = new URL(urlString);

    // Verify it's a GitHub URL
    const hostname = url.hostname.toLowerCase();
    if (hostname !== "github.com" && hostname !== "www.github.com") {
      // Not a GitHub URL, fall through to owner/repo parsing
      throw new Error("Not a GitHub URL");
    }

    // Parse path: /owner/repo or /owner/repo/...
    const pathParts = url.pathname.split("/").filter((part) => part.length > 0);

    if (pathParts.length < 2) {
      return {
        error:
          "GitHub URL must include both owner and repository (e.g., https://github.com/owner/repo)",
      };
    }

    const owner = pathParts[0];
    const repo = pathParts[1];

    // Validate owner and repo names
    if (!isValidGithubName(owner)) {
      return { error: `Invalid GitHub owner name: ${owner}` };
    }
    if (!isValidGithubName(repo)) {
      return { error: `Invalid GitHub repository name: ${repo}` };
    }

    return { owner, repo };
  } catch (urlError) {
    // Not a valid URL, try parsing as owner/repo or just owner
    const parts = cleaned.split("/").filter((part) => part.length > 0);

    if (parts.length === 1) {
      // Just owner provided
      const owner = parts[0];
      if (!isValidGithubName(owner)) {
        return { error: `Invalid GitHub owner name: ${owner}` };
      }
      // Return owner with empty repo - this will be handled by the form
      return { owner, repo: "" };
    } else if (parts.length === 2) {
      // owner/repo format
      const owner = parts[0];
      const repo = parts[1];

      if (!isValidGithubName(owner)) {
        return { error: `Invalid GitHub owner name: ${owner}` };
      }
      if (!isValidGithubName(repo)) {
        return { error: `Invalid GitHub repository name: ${repo}` };
      }

      return { owner, repo };
    } else {
      return {
        error:
          "Invalid format. Expected: GitHub URL (https://github.com/owner/repo), owner/repo, or just owner",
      };
    }
  }
}

/**
 * Parse a comma or newline-separated list of GitHub repositories
 * Each item can be:
 * - A full GitHub URL: https://github.com/owner/repo
 * - owner/repo format: owner1/repo1,owner2/repo2
 *
 * @param input - Comma or newline-separated string of repositories
 * @returns Array of owner/repo strings (e.g., ["microsoft/vscode", "vercel/next.js"])
 */
export function parseGithubRepositories(input: string): string[] | ParseError {
  if (!input || typeof input !== "string") {
    return [];
  }

  const trimmed = input.trim();
  if (!trimmed) {
    return [];
  }

  // Split by comma or newline and trim each part
  const parts = trimmed
    .split(/[,\n]/)
    .map((part) => part.trim())
    .filter((part) => part.length > 0);

  const results: string[] = [];

  for (const part of parts) {
    const parsed = parseGithubUrl(part);

    if ("error" in parsed) {
      return { error: `Invalid repository format: ${part}. ${parsed.error}` };
    }

    // Must have both owner and repo
    if (!parsed.repo) {
      return { error: `Repository name required. Got only owner: ${part}` };
    }

    // Always return in owner/repo format for consistency
    results.push(`${parsed.owner}/${parsed.repo}`);
  }

  return results;
}

/**
 * Validate a GitHub username or repository name
 * GitHub names can contain alphanumeric characters and hyphens
 * Cannot start or end with a hyphen
 * Maximum 39 characters for usernames, 100 for repos
 *
 * @param name - The name to validate
 * @returns true if valid, false otherwise
 */
function isValidGithubName(name: string): boolean {
  if (!name || typeof name !== "string") {
    return false;
  }

  const trimmed = name.trim();

  // Check length (being permissive with max length)
  if (trimmed.length === 0 || trimmed.length > 100) {
    return false;
  }

  // Check for valid characters: alphanumeric, hyphens, underscores, dots
  // GitHub repos can have these characters, but not start/end with special chars
  const validPattern = /^[a-zA-Z0-9][a-zA-Z0-9._-]*[a-zA-Z0-9]$/;
  const singleCharPattern = /^[a-zA-Z0-9]$/; // Single character names are valid

  return singleCharPattern.test(trimmed) || validPattern.test(trimmed);
}

/**
 * Check if a string looks like a GitHub URL
 *
 * @param input - String to check
 * @returns true if it looks like a GitHub URL
 */
export function isGithubUrl(input: string): boolean {
  if (!input || typeof input !== "string") {
    return false;
  }

  const trimmed = input.trim().toLowerCase();
  return trimmed.includes("github.com");
}
