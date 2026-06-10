export interface UseCaseValidateParams {
  useCaseName: string;
  prompt?: string;
}

export interface ValidationResult {
  valid: boolean;
  missingFields: string[];
}

export async function useCaseValidate(params: UseCaseValidateParams): Promise<ValidationResult> {
  // TODO: implement prompt ↔ schema validation
  return { valid: true, missingFields: [] };
}
