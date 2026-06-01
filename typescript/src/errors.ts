/**
 * Error taxonomy mirroring the Python package.
 *
 * The Python implementation defines these next to the module that raises them
 * (`AuthError` in auth.py, `APIError` in api.py, `NoSubscriptionError` in
 * quota.py). Centralizing them here keeps the TypeScript modules free of import
 * cycles while preserving identical raise/catch semantics.
 */

export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

export class APIError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "APIError";
  }
}

export class NoSubscriptionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "NoSubscriptionError";
  }
}
