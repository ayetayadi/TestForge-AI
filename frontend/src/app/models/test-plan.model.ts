// ============================================================
// TEST PLAN MODELS
// ============================================================

export type TestPlanStatus = 'draft' | 'ai_proposed' | 'approved' | 'active' | 'archived';

export interface TestPlan {
  id: string;
  project_id: string;
  project_name?: string;
  project_key?: string;
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
  status: TestPlanStatus;
  ai_draft_generated_at?: string;
  approved_at?: string;
  generation_completed_at?: string;
  created_at: string;
  updated_at: string;
  risk_analysis?: RiskAnalysisDisplay;
  estimation?: PertEstimationDisplay;
  recommendations_detail?: RecommendationsDetail;
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
  // ✅ Nouveaux champs pour filtrage
  sprint_ids?: string[];
  epic_keys?: string[];
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

// ============================================================
// RISK ANALYSIS DISPLAY (visible dans le Test Plan)
// ============================================================

export interface RiskMappingEntry {
  issue_key: string;
  title: string;
  risk_level: string;
  risk_score: number;
  risk_description?: string;
  probability?: number;
  impact?: number;
}

export interface RiskDistribution {
  critical: number;
  high: number;
  medium: number;
  low: number;
  total: number;
  high_risk_ratio: number;
}

export interface RiskFormulas {
  risk_score: string;
  probability_scale: string;
  impact_scale: string;
  thresholds: {
    critical: string;
    high: string;
    medium: string;
    low: string;
  };
}

export interface RiskAnalysisDisplay {
  distribution: RiskDistribution;
  formulas: RiskFormulas;
  mapping_table: RiskMappingEntry[];
  top_risks: string[];
}

// ============================================================
// PERT ESTIMATION DISPLAY
// ============================================================

export interface PertBreakdownEntry {
  level: string;
  story_count: number;
  days_per_story_optimistic: number;
  days_per_story_realistic: number;
  days_per_story_pessimistic: number;
  subtotal_optimistic: number;
  subtotal_realistic: number;
  subtotal_pessimistic: number;
}

export interface PertEstimationDisplay {
  formula: string;
  inputs: {
    optimistic: number;
    most_likely: number;
    pessimistic: number;
  };
  calculation: string;
  standard_deviation: string;
  confidence_interval: string;
  breakdown_by_risk: PertBreakdownEntry[];
}

// ============================================================
// RECOMMENDATIONS DISPLAY
// ============================================================

export interface RecommendationsDetail {
  test_types: string[];
  test_levels: string[];
  reasoning: string[];
}