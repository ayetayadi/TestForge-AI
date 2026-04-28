// ============================================================
// TEST PLAN MODELS
// ============================================================

export type TestPlanStatus = 'draft' | 'ai_proposed' | 'approved' | 'active' | 'archived';

export interface TestPlan {
  id: string;
  project_id: string;
  title: string;
  description?: string;
  objective?: string;
  scope_type?: string;
  scope_refs: string[];
  in_scope?: string;
  out_of_scope?: string;
  test_types: string[];
  test_levels: string[];
  environment?: string;
  start_date?: string;
  end_date?: string;
  entry_criteria?: string;
  exit_criteria?: string;
  approach?: string;
  assumptions?: string;
  constraints?: string;
  stakeholders?: string;
  communication?: string;
  matrix_snapshot?: Record<string, any>;
  coverage_snapshot?: Record<string, any>;
  status: TestPlanStatus;
  ai_draft_generated_at?: string;
  approved_at?: string;
  generation_completed_at?: string;
  created_at: string;
  updated_at: string;
}

export interface TestPlanListResponse {
  items: TestPlan[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ============================================================
// STATUS CONFIG (colors, labels, icons)
// ============================================================

export interface TestPlanStatusConfig {
  label: string;
  color: string;
  bg: string;
  icon: string;
}

export const TEST_PLAN_STATUS_CONFIG: Record<TestPlanStatus, TestPlanStatusConfig> = {
  draft: {
    label: 'Draft',
    color: '#6c757d',
    bg: '#f8f9fa',
    icon: 'solar:document-line-duotone',
  },
  ai_proposed: {
    label: 'AI Proposed',
    color: '#7b5ea7',
    bg: '#f3eeff',
    icon: 'solar:magic-stick-3-line-duotone',
  },
  approved: {
    label: 'Approved',
    color: '#198754',
    bg: '#d1e7dd',
    icon: 'solar:check-circle-line-duotone',
  },
  active: {
    label: 'Active',
    color: '#0d6efd',
    bg: '#cfe2ff',
    icon: 'solar:play-circle-line-duotone',
  },
  archived: {
    label: 'Archived',
    color: '#6c757d',
    bg: '#e9ecef',
    icon: 'solar:archive-line-duotone',
  },
};

// ============================================================
// REQUEST / RESPONSE TYPES
// ============================================================

export interface GenerateTestPlanRequest {
  project_id: string;
  scope_type?: string;
  scope_refs?: string[];
  environment?: string;
  limit_risks?: number;
  limit_stories?: number;
}

export interface GenerateTestPlanResponse {
  test_plan: TestPlan;
  recommendations?: Record<string, any>;
  workflow_status: string;
}

export interface TestPlanUpdate {
  title?: string;
  description?: string;
  objective?: string;
  scope_type?: string;
  scope_refs?: string[];
  in_scope?: string;
  out_of_scope?: string;
  test_types?: string[];
  test_levels?: string[];
  environment?: string;
  start_date?: string;
  end_date?: string;
  entry_criteria?: string;
  exit_criteria?: string;
  approach?: string;
  assumptions?: string;
  constraints?: string;
  stakeholders?: string;
  communication?: string;
}

export interface TestPlanSummary {
  total: number;
  by_status: Partial<Record<TestPlanStatus, number>>;
  approved: number;
  pending: number;
}

// ============================================================
// EMAIL SHARING
// ============================================================

export interface EmailRecipient {
  email: string;
  role: string;
  name?: string;
}

export interface SendEmailRequest {
  recipients: EmailRecipient[];
  subject?: string;
  body?: string;
  generate_body?: boolean;
  sender_name?: string;
}

export interface GenerateEmailBodyRequest {
  recipients: EmailRecipient[];
  additional_context?: string;
}

export interface GenerateEmailBodyResponse {
  subject: string;
  body: string;
}

export interface SendEmailResponse {
  sent_to: string[];
  subject: string;
  message: string;
}

// ============================================================
// JIRA NOTIFICATION
// ============================================================

export interface JiraNotificationRequest {
  project_key: string;
  summary?: string;
  description?: string;
  issue_type?: string;
  priority?: string;
}

export interface JiraNotificationResponse {
  issue_key: string;
  issue_url: string;
  summary: string;
  message: string;
}
