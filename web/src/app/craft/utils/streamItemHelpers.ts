/**
 * Stream Item Helpers
 *
 * Reduced to only utility functions that are NOT packet-processing concerns.
 * All packet parsing, tool detection, and path sanitization now live in parsePacket.ts.
 */

/**
 * Generate a unique ID for stream items
 */
export function genId(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}
