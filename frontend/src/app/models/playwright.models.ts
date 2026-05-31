export enum ScriptSource {
  V1_DRAFT = "v1_draft",
  V2_CORRECTED = "v2_corrected",
  MANUAL_EDIT = "manual_edit",
  AI_FIX = "ai_fix"
}

export enum ScriptValidationStatus {
  NOT_VALIDATED = "not_validated",
  VALID = "valid",
  INVALID = "invalid",
  DRAFT = "draft"
}

export enum TestExecutionStatus {
  RUNNING   = "running",
  COMPLETED = "completed",
  ABORTED   = "aborted",
}

export enum TestCaseResultStatus {
  PASSED  = "passed",
  FAILED  = "failed",
  ERROR   = "error",
  SKIPPED = "skipped",
}

// ── Legacy alias enums (kept so existing components compile) ────────
export enum TestRunStatus {
  RUNNING   = "running",
  COMPLETED = "completed",
  ABORTED   = "aborted",
}

export enum TestResultStatus {
  PASSED  = "passed",
  FAILED  = "failed",
  ERROR   = "error",
  SKIPPED = "skipped",
}

export enum StepType {
  THINK = "think",
  ACT = "act",
  OBSERVE = "observe"
}

export enum StepStatus {
  SUCCESS = "success",
  FAILED = "failed",
  PENDING = "pending",  
  RUNNING = "running"   
}

export type ExecutionStatus = 'passed' | 'failed' | 'completed' | 'error';

// ============================================================
// REQUEST MODELS
// ============================================================

export interface GenerateScriptRequest {
  test_case_id: string;
  app_url?: string;
  model_id?: string;
}

export interface UpdateScriptRequest {
  script_content: string;
}

export interface UpdateScriptResponse {
  id: string;
  version_number: number;
  source: string;
  is_active: boolean;
  placeholder_count: number;
  validation_status: string;
  created_at: string | null;
}

export interface ExecuteScriptRequest {
  test_case_id: string;
  script_version_id?: string;
  app_url?: string;
  browser?: 'chromium' | 'firefox' | 'webkit';
  headless?: boolean;
  model_id?: string;
}

export interface FullWorkflowRequest {
  test_case_id: string;
  app_url?: string;
  browser?: 'chromium' | 'firefox' | 'webkit';
  headless?: boolean;
  model_id?: string;
}

// ============================================================
// RESPONSE MODELS
// ============================================================

export interface GenerateScriptResponse {
  status: 'generated' | 'error';
  script_v1: string;
  placeholder_count: number;
  model_used: string;
  script_version_id?: string;
  version_number?: number;
  warning?: string;
  error?: string;
}

export interface ExecuteScriptResponse {
  status: string;
  script_v2?: string;
  execution_status?: ExecutionStatus;
  steps_passed: number;
  steps_failed: number;
  remaining_placeholders: number;
  test_run_id?: string;
  script_version_id?: string;
  error?: string;
}

export interface FullWorkflowResponse {
  workflow_status: 'completed' | 'generation_failed' | 'execution_failed';
  generation: {
    status: string;
    placeholder_count: number;
    script_version_id?: string;
  };
  execution: {
    status?: string;
    steps_passed: number;
    steps_failed: number;
    remaining_placeholders: number;
    test_run_id?: string;
    script_version_id?: string;
  };
  summary: {
    total_steps: number;
    passed_steps: number;
    failed_steps: number;
    success_rate: number;
  };
}

export interface ScriptInfo {
  id: string;
  version_number: number;
  source: string;
  is_active: boolean;
  placeholder_count: number;
  validation_status: string;
  created_at: string;
}

export interface ScriptListResponse {
  test_case_id: string;
  active_script_id: string | null;
  scripts: ScriptInfo[];
}

export interface TestStepResult {
  order: number;
  type: StepType;
  content: string;
  tool_name?: string;
  status: StepStatus;
  duration?: number;
  error_message?: string;
  timestamp: string;
}

export interface TestResultDetails {
  id?: string;
  test_run_id?: string;
  status: TestResultStatus | null;
  justification?: string;
  error_message?: string;
  steps_passed?: number;
  steps_failed?: number;
  duration?: number;
  total_steps?: number;
  script_version_id?: string;
  script_v2?: string;
  created_at?: string;
  updated_at?: string;
}

export interface TestRunDetails {
  id: string;
  status: TestRunStatus;
  browser: string;
  headless: boolean;
  started_at: string;
  completed_at: string | null;
  duration?: number;
}

export interface TestRunDetailsResponse {
  test_run: TestRunDetails;
  result: TestResultDetails | null;
  steps: TestStepResult[];
}

export interface LastRunResponse {
  test_run?: TestRunDetails;
  result?: TestResultDetails;
  steps?: TestStepResult[];
  error?: string;
  message?: string;
}

export interface HealthCheckResponse {
  status: string;
  mcp_server_url: string;
  agents: {
    script_generator: string;
    react_agent: string;
  };
}

export interface AsyncStartResponse {
  status: string;
  test_case_id: string;
  message: string;
}

export type PlaywrightSSEEventType =
  | 'generation_started'
  | 'generation_completed'
  | 'generation_failed'
  | 'execution_started'
  | 'agent_step'
  | 'completed'
  | 'failed'
  | 'ping';

export interface PlaywrightSSEEvent {
  type: PlaywrightSSEEventType;
  data: Record<string, any>;
  timestamp: string;
}

// ============================================================
// UI MODELS (pour l'affichage)
// ============================================================

export type ExecutionStepStatus = 'success' | 'failed' | 'pending' | 'running';

export interface ExecutionStep {
  order: number;
  type: 'think' | 'act' | 'observe';
  content: string;
  toolName?: string;
  status: ExecutionStepStatus;
  duration?: number;
  locatorFound?: string;  // Pour l'affichage des locators découverts
  timestamp: Date;
}

export interface DiscoveredLocator {
  placeholder: string;
  selector: string;
  strategy: string;  // data-testid, css, xpath, etc.
  confidence: 'high' | 'medium' | 'low';
}

export interface ScriptVersionUI {
  id: string;
  versionNumber: number;
  isActive: boolean;
  source: string;
  validationStatus: string;
  placeholderCount: number;
  createdAt: Date;
  content?: string;
}

// ============================================================
// TEST EXECUTION / TEST CASE RESULT  (nouveau modèle backend)
// ============================================================

export interface TcResultStep {
  order: number;
  type: 'think' | 'act' | 'observe' | string;
  tool_name?: string | null;
  content: string;
  status: 'success' | 'failed' | string;
  error?: string | null;
  duration?: number | null;
}

export interface TestCaseResultBasic {
  id: string;
  test_case_id: string;
  tc_code?: string | null;
  title?: string | null;
  execution_order: number;
  status: string;
  duration?: number | null;
  steps_passed: number;
  steps_failed: number;
}

export interface TestCaseResultDetail extends TestCaseResultBasic {
  steps: TcResultStep[];
  justification?: string | null;
  error_message?: string | null;
  screenshot_b64?: string | null;
  script_version_id?: string | null;
  script_source?: string | null;
  script_version_number?: number | null;
  script_placeholder_count?: number | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface TestExecutionBasic {
  id: string;
  suite_id: string;
  suite_title?: string | null;
  project_name?: string | null;
  app_url: string;
  browser: string;
  headless: boolean;
  status: string;
  started_at: string;
  completed_at?: string | null;
  duration?: number | null;
  total_count: number;
  passed_count: number;
  failed_count: number;
  skipped_count: number;
  error_count: number;
  triggered_by_email?: string | null;
  is_closed: boolean;
  closed_at?: string | null;
}

export interface TestExecutionDetail extends TestExecutionBasic {
  stop_on_failure?: boolean;
  model_id?: string | null;
  test_case_results: TestCaseResultDetail[];
}

export interface TestExecutionGlobalStats {
  total_runs: number;
  running: number;
  passed: number;
  failed: number;
  skipped: number;
  error: number;
  pass_rate: number;       // %
  avg_duration: number;    // seconds
}

export interface TestExecutionListResponse {
  items: TestExecutionBasic[];
  total: number;
  stats: TestExecutionGlobalStats;
}