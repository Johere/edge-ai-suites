/**
 * Parse structured key-value fields from a VLM summary text.
 *
 * Supports the common "KEY: value" line format (e.g. SEVERITY: critical).
 * Field names are user-defined via schema extensions — this function makes
 * no assumptions about which keys exist; it returns all key-value pairs found.
 *
 * Matching is case-insensitive on keys; values are returned as-is (trimmed).
 *
 * Example input:
 *   "SEVERITY: critical\nEVENT: fall\nDESC: Person fell from chair"
 *
 * Example output:
 *   { severity: "critical", event: "fall", desc: "Person fell from chair" }
 */
export function parseSummaryFields(summaryText: string): Record<string, string> {
  const result: Record<string, string> = {};
  if (!summaryText) return result;

  for (const line of summaryText.split("\n")) {
    const colon = line.indexOf(":");
    if (colon < 1) continue;
    const key = line.slice(0, colon).trim().toLowerCase();
    const value = line.slice(colon + 1).trim();
    if (key && value && !result[key]) {
      // First occurrence wins (consistent with design doc §7)
      result[key] = value;
    }
  }

  return result;
}
