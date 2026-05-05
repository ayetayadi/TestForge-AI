// ============================================================
// TEST SUITE MODELS
// ============================================================

export type SuiteType =
  | 'feature' | 'epic' | 'sprint' | 'smoke' | 'regression'
  | 'negative' | 'security' | 'performance' | 'e2e';

export type SuiteStatus = 'draft' | 'active' | 'archived' | 'closed';

export type Priority = 'critical' | 'high' | 'medium' | 'low';

export type DependencyType = 'requires' | 'blocks' | 'related';

// ── Embedded: Test Case ────────────────────────────────────────

export interface TestStep {
  order: number;
  action: string;
  expected: string;
}

export interface EmbeddedTestCase {
  id: string;
  tc_code: string;
  title: string;
  description?: string | null;
  test_type?: string | null;
  priority?: Priority | null;
  tags: string[];
  preconditions: string[];
  postconditions: string[];
  steps: TestStep[];
  gherkin_source?: string | null;
  test_data: Record<string, unknown>;
  expected_results: string[];
  risk_ids: string[];
  execution_order?: number | null;
  user_story_id?: string | null;
  test_suite_id?: string | null;
  is_active: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  priority_score: number;
}

// ── Embedded: Risk ─────────────────────────────────────────────

export interface EmbeddedRisk {
  id: string;
  description: string;
  level?: Priority | null;
  risk_score?: number | null;
  probability?: number | null;
  impact?: number | null;
  mitigation?: string | null;
  is_accepted: boolean | null;
  user_story_id?: string | null;  // 🆕 Pour lier à l'US
}

// ── Embedded: Test Plan ────────────────────────────────────────

export interface EmbeddedTestPlan {
  id: string;
  title: string;
  status: string | null;
  objective?: string | null;
  in_scope?: string | null;
  out_of_scope?: string | null;
  environment?: string | null;
  entry_criteria?: string | null;
  exit_criteria?: string | null;
  approach?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  approved_at?: string | null;
}

// ── RISK COVERAGE (TestSuite level) ────────────────────────────

export interface RiskCoverage {
  risk_coverage_pct: number;        // 0-100
  covered_risks: number;
  total_risks: number;
  uncovered_risk_ids: string[];
  mitigation_status: 'fully_mitigated' | 'partially_mitigated' | 'not_mitigated';
}

// ── AC COVERAGE PER US (within TestSuite) ──────────────────────

export interface UsAcCoverage {
  user_story_id: string;
  issue_key: string;
  title: string;
  ac_coverage_pct: number;      // 0-100
  covered_ac: number;
  total_ac: number;
  uncovered_ac: string[];
  is_sufficient: boolean;
  has_tests: boolean;
}

// ── Traceability Matrix ────────────────────────────────────────

export interface TraceabilityACRow {
  ac_index: number;
  ac_text: string;
  covered_by: string[];
  is_covered: boolean;
}

export interface TraceabilityStoryRow {
  user_story_id: string;
  issue_key: string;
  title: string;
  acceptance_criteria: TraceabilityACRow[];
  covered_cases: number;
  total_ac: number;
  coverage_pct: number;
}

export interface TraceabilityMatrix {
  rows: TraceabilityStoryRow[];
  total_stories: number;
  total_ac: number;
  covered_ac: number;
  global_coverage_pct: number;
}

// ── Dependency Graph ───────────────────────────────────────────

export interface DependencyNode {
  id: string;
  tc_code: string;
  title: string;
  business_flow?: string | null;
  priority?: Priority | null;
  test_type?: string | null;
  execution_order?: number | null;
}

export interface DependencyEdge {
  source: string;
  target: string;
  source_id: string;
  target_id: string;
  dependency_type: DependencyType;
  is_ai_generated: boolean;
}

export interface DependencyGraph {
  nodes: DependencyNode[];
  edges: DependencyEdge[];
  execution_order: string[];
}

// ── Lifecycle ──────────────────────────────────────────────────

export interface SuiteLifecycle {
  risk_analysis: {
    total_risks: number;
    distribution: Record<string, number>;
    accepted_count: number;
  };
  test_plan: {
    id: string | null;
    title: string | null;
    status: string | null;
    approved_at?: string | null;
    environment?: string | null;
    entry_criteria?: string | null;
    exit_criteria?: string | null;
  };
  test_suite: {
    id: string;
    title: string;
    type?: string | null;
    priority?: string | null;
    is_ai_generated: boolean;
    created_at?: string | null;
  };
  test_cases: {
    total: number;
    active: number;
    with_gherkin: number;
  };
}

// ── Priority Reasoning ─────────────────────────────────────────

export interface PriorityReasoning {
  risk_weight: number;
  risk_breakdown: Record<string, number>;
  coverage_ac_count: number;
  coverage_total_ac: number;
  requirement_order: number;
  priority_formula: string;
  execution_order_reason: string;
}

// ── All Suites Order ───────────────────────────────────────────

export interface SuiteOrderEntry {
  id: string;
  title: string;
  execution_order: number | null;
  priority: string | null;
  test_case_count: number;
}

// ============================================================
// LIST ITEM
// ============================================================

export interface TestSuiteListItem {
  id: string;
  test_plan_id: string;
  title: string;
  description?: string | null;
  suite_type?: SuiteType | null;
  priority?: Priority | null;
  status: SuiteStatus;
  execution_order?: number | null;
  is_ai_generated: boolean;
  test_case_count: number;
  project_name?: string | null;
  project_key?: string | null;
  test_plan_title?: string | null;
  test_plan_status?: string | null;
  
  // 🆕 Couverture dans la liste
  risk_coverage?: RiskCoverage;
  
  created_at?: string | null;
  updated_at?: string | null;
}

// ============================================================
// DETAIL (UN SEUL - PAS DE DOUBLON)
// ============================================================

export interface TestSuiteDetail {
  id: string;
  test_plan_id: string;
  title: string;
  description?: string | null;
  suite_type?: SuiteType | null;
  priority?: Priority | null;
  status: SuiteStatus;
  execution_order?: number | null;
  is_ai_generated: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  
  // Context
  test_plan?: EmbeddedTestPlan | null;
  project_id?: string | null;
  project_name?: string | null;
  project_key?: string | null;
  
  // Content
  test_cases: EmbeddedTestCase[];
  risks: EmbeddedRisk[];
  
  // 🆕 COUVERTURES (remplacent l'ancien "coverage: SuiteCoverage")
  risk_coverage: RiskCoverage;              // Globale TestSuite
  us_ac_coverages: UsAcCoverage[];         // Par US
  
  // Analysis
  traceability_matrix: TraceabilityMatrix | null;
  dependency_graph: DependencyGraph | null;
  lifecycle: SuiteLifecycle;
  priority_reasoning?: PriorityReasoning | null;
  all_suites_order: SuiteOrderEntry[];
}

// ============================================================
// LIST RESPONSE
// ============================================================

export interface TestSuiteListResponse {
  items: TestSuiteListItem[];
  total: number;
}

// ── Requests ──────────────────────────────────────────────────

export interface GenerateTestSuitesRequest {
  test_plan_id: string;
  strategy: string;
  project_name: string;
}

export interface GenerateTestSuitesResponse {
  suites: {
    id: string;
    title: string;
    execution_order: number;
    tc_count: number;
    risk_coverage_pct: number;
    mitigation_status: string;
  }[];
  count: number;
  strategy: string;
  risk_coverage: RiskCoverage;
  workflow_status: string;
  error?: string | null;
}

export interface UpdateTestSuiteRequest {
  title?: string;
  description?: string | null;
  suite_type?: SuiteType | null;
  priority?: Priority | null;
  status?: SuiteStatus;
  execution_order?: number | null;
}

export interface AssignTestCaseRequest {
  test_case_id: string;
  suite_id: string;
}

export interface UnassignTestCaseRequest {
  test_case_id: string;
}

// ============================================================
// UI CONFIGS
// ============================================================

export const SUITE_TYPE_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  negative:    { label: 'Negative', color: '#ef4444', bg: '#fee2e2' },
  positive:    { label: 'Positive', color: '#16a34a', bg: '#dcfce7' },
  boundary:    { label: 'Boundary', color: '#8b8b8b', bg: '#f3f4f6' },
};

export const SUITE_STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  draft:    { label: 'Draft',    color: '#6b7280', bg: '#f3f4f6' },
  active:   { label: 'Active',   color: '#10b981', bg: '#d1fae5' },
  archived: { label: 'Archived', color: '#f59e0b', bg: '#fef3c7' },
  closed:   { label: 'Closed',   color: '#ef4444', bg: '#fee2e2' },
};

export const PRIORITY_CONFIG: Record<string, { label: string; color: string; bg: string; dot: string }> = {
  critical: { label: 'Critical', color: '#dc2626', bg: '#fee2e2', dot: '#ef4444' },
  high:     { label: 'High',     color: '#ea580c', bg: '#ffedd5', dot: '#f97316' },
  medium:   { label: 'Medium',   color: '#ca8a04', bg: '#fef9c3', dot: '#eab308' },
  low:      { label: 'Low',      color: '#16a34a', bg: '#dcfce7', dot: '#22c55e' },
};

export const MITIGATION_STATUS_CONFIG: Record<string, { label: string; color: string; bg: string }> = {
  fully_mitigated:     { label: 'Fully Mitigated',     color: '#16a34a', bg: '#dcfce7' },
  partially_mitigated: { label: 'Partially Mitigated', color: '#ca8a04', bg: '#fef9c3' },
  not_mitigated:       { label: 'Not Mitigated',       color: '#dc2626', bg: '#fee2e2' },
};