export interface SchemaExtension {
  name: string;
  type: "text" | "integer" | "real";
  required: boolean;
}

export interface SchemaDefinition {
  video_summary_tasks?: { extensions: SchemaExtension[] };
  alerts?: { extensions: SchemaExtension[] };
  custom_tables?: Array<{ name: string; columns: SchemaExtension[] }>;
}

/**
 * Manages DB schema customization based on YAML declarations.
 * On startup: compares declared schema with actual DB columns,
 * applies ALTER TABLE ADD COLUMN for new fields.
 */
export class SchemaManager {
  async applySchema(schema: SchemaDefinition): Promise<void> {
    // TODO: compare declared vs actual, apply migrations
  }

  async validatePromptSchema(
    requiredFields: string[],
    prompt: string,
  ): Promise<{ valid: boolean; missing: string[] }> {
    const missing = requiredFields.filter(
      (field) => !prompt.toLowerCase().includes(field.toLowerCase()),
    );
    return { valid: missing.length === 0, missing };
  }
}
