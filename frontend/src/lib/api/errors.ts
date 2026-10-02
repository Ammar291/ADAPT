import { tr } from "@/i18n";
/**
 * RFC 9457 problem details, as every ADAPT API error is shaped. Declared here (not imported
 * from the generated contracts) so error handling survives contract regeneration.
 */
export interface ProblemDetail {
  type?: string;
  title: string;
  status: number;
  code: string;
  detail?: string | null;
  instance?: string | null;
  request_id?: string | null;
  errors?: { loc: string[]; message: string; type: string }[] | null;
  extra?: Record<string, unknown> | null;
}

export function isProblemDetail(value: unknown): value is ProblemDetail {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as ProblemDetail).status === "number" &&
    typeof (value as ProblemDetail).code === "string" &&
    typeof (value as ProblemDetail).title === "string"
  );
}

/**
 * Every failed request (live or mock) surfaces as an `ApiError`. Branch on `code`
 * (stable, from the backend's problem details), never on `message`.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly title: string;
  readonly detail: string | null;
  readonly requestId: string | null;
  readonly fieldErrors: { loc: string[]; message: string; type: string }[];
  readonly extra: Record<string, unknown>;

  constructor(problem: ProblemDetail) {
    super(problem.detail ?? problem.title);
    this.name = "ApiError";
    this.status = problem.status;
    this.code = problem.code;
    this.title = problem.title;
    this.detail = problem.detail ?? null;
    this.requestId = problem.request_id ?? null;
    this.fieldErrors = problem.errors ?? [];
    this.extra = problem.extra ?? {};
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }

  get isNetwork(): boolean {
    return this.code === "network_error" || this.code === "timeout";
  }

  /** Worth retrying automatically (transient server or network conditions). */
  get isRetryable(): boolean {
    return this.isNetwork || this.status === 502 || this.status === 503 || this.status === 504;
  }

  static network(message: string, code: "network_error" | "timeout" = "network_error"): ApiError {
    return new ApiError({ title: message, status: 0, code });
  }

  static fromResponse(status: number, body: unknown, requestId: string | null): ApiError {
    if (isProblemDetail(body)) return new ApiError(body);
    return new ApiError({
      title: status >= 500 ? tr("copy.the_server_had_a_problem_512f692") : tr("copy.the_request_failed_02d6745"),
      status,
      code: `http_${status}`,
      request_id: requestId,
    });
  }
}

export function isApiError(error: unknown, code?: string): error is ApiError {
  return error instanceof ApiError && (code === undefined || error.code === code);
}

/** Human-readable, interface-voice explanation for an error of any origin. */
export function describeError(error: unknown): { title: string; detail: string } {
  if (error instanceof ApiError) {
    if (error.isNetwork) {
      return {
        title: tr("copy.can_t_reach_adapt_e425d07"),
        detail: tr("copy.check_your_connection_your_work_is_safe_and_will_645abd9"),
      };
    }
    if (error.status >= 500) {
      return {
        title: error.title,
        detail: error.requestId
          ? `Try again in a moment. Reference: ${error.requestId.slice(0, 8)}`
          : tr("copy.try_again_in_a_moment_288edef"),
      };
    }
    return { title: error.title, detail: error.detail ?? "" };
  }
  if (error instanceof Error && error.name === "CapabilityUnavailableError") {
    return { title: tr("copy.this_isn_t_available_yet_549211e"), detail: tr("copy.it_will_appear_here_as_soon_as_it_s_switched_on_96307ea") };
  }
  return { title: tr("copy.something_went_wrong_8d886c0"), detail: tr("copy.reload_the_page_to_try_again_d664908") };
}
