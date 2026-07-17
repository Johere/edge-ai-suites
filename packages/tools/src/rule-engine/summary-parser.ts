import type { SchemaExtension } from "@smartbuilding-video/db";

export interface ParsedSummary {
  /** Fields successfully extracted from the summary text, keyed by lowercased schema field name. */
  fields: Record<string, string>;
  /** Names of required fields (schema.required:true) that were NOT found in the summary. */
  missingRequired: string[];
}

/**
 * Schema-aware parser for VLM summary output.
 *
 * Uses the schema `extensions` array as the source of truth — only field names
 * declared there are parsed; lines starting with other keys are ignored.
 *
 * Matching is case-insensitive: a schema field `event` matches `EVENT:`, `Event:`, or `event:`.
 * First occurrence wins when duplicates appear.
 *
 * `requiredFields` (optional) overrides which fields count as required for the
 * `missingRequired` check — pass the current use case's effective required set so
 * one use case's required fields don't get flagged as missing on another's tasks.
 * When omitted, falls back to the global `extensions` required flags.
 */
export function parseSummaryFields(
  summaryText: string,
  extensions: SchemaExtension[],
  requiredFields?: string[],
): ParsedSummary {
  const requiredNames = requiredFields ?? extensions.filter((e) => e.required).map((e) => e.name);
  const fields: Record<string, string> = {};
  if (!summaryText || extensions.length === 0) {
    return { fields, missingRequired: [...requiredNames] };
  }

  // Build lookup: lowercased schema name → canonical (lowercased) name to store under
  const wanted = new Map<string, string>();
  for (const ext of extensions) wanted.set(ext.name.toLowerCase(), ext.name.toLowerCase());

  for (const line of summaryText.split("\n")) {
    const colon = line.indexOf(":");
    if (colon < 1) continue;
    const key = line.slice(0, colon).trim().toLowerCase();
    const canonical = wanted.get(key);
    if (!canonical) continue; // not a schema field — skip
    if (fields[canonical]) continue; // first occurrence wins
    const value = line.slice(colon + 1).trim();
    if (value) fields[canonical] = value;
  }

  const missingRequired = requiredNames.filter((name) => !fields[name.toLowerCase()]);

  return { fields, missingRequired };
}
