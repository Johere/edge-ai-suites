export interface UseCaseValidateParams {
  use_case: string;
  prompt: string;
  required_fields: string[];
}

export interface ValidationResult {
  valid: boolean;
  use_case: string;
  missing_fields: string[];
  checked_fields: string[];
}

/**
 * Validate that all required schema fields are present in the video summary prompt.
 * Matching is case-insensitive substring search.
 * Returns missing fields so the caller knows exactly what to fix.
 */
export function useCaseValidate(params: UseCaseValidateParams): ValidationResult {
  const promptLower = params.prompt.toLowerCase();
  const missing = params.required_fields.filter(
    (field) => !promptLower.includes(field.toLowerCase())
  );
  return {
    valid: missing.length === 0,
    use_case: params.use_case,
    missing_fields: missing,
    checked_fields: params.required_fields,
  };
}
