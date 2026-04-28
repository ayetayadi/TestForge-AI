export type RiskLevel = 'critical' | 'high' | 'medium' | 'low';

export interface Risk {
  id: string;
  project_id: string;
  test_plan_id: string | null;
  user_story_id: string | null;
  user_story_key?: string | null;
  user_story_title?: string | null;
  description: string;
  mitigation: string | null;
  reasoning: string | null;
  probability: number;
  impact: number;
  risk_score: number;
  level: RiskLevel;
  is_ai_generated: boolean;
  is_accepted: boolean | null;
  created_at: string;
  source?: 'original' | 'approved_version';
  source_version_id?: string;
  source_story_text?: string;
  source_acceptance_criteria?: string;
}

export interface RiskSummary {
  total: number;
  by_level: Record<RiskLevel, number>;
  avg_score: number;
  accepted_count: number;
  rejected_count: number;
  pending_count: number;
}

export interface TestPlan {
  id: string;
  title: string;
  status: string;
  created_at: string;
}

export interface RiskMatrixCell {
  row: number;
  col: number;
  level: RiskLevel;
  bgScore: number;
  risks: Risk[];
}

export const RISK_LEVEL_CONFIG: Record<RiskLevel, {
  label: string;
  color: string;
  bg: string;
  border: string;
  textClass: string;
  matrixBg: string;
}> = {
  critical: {
    label: 'Critical',
    color: '#dc2626',
    bg: '#fef2f2',
    border: '#fca5a5',
    textClass: 'level-critical',
    matrixBg: 'rgba(220, 38, 38, 0.85)',
  },
  high: {
    label: 'High',
    color: '#ea580c',
    bg: '#fff7ed',
    border: '#fdba74',
    textClass: 'level-high',
    matrixBg: 'rgba(234, 88, 12, 0.80)',
  },
  medium: {
    label: 'Medium',
    color: '#d97706',
    bg: '#fffbeb',
    border: '#fcd34d',
    textClass: 'level-medium',
    matrixBg: 'rgba(217, 119, 6, 0.70)',
  },
  low: {
    label: 'Low',
    color: '#16a34a',
    bg: '#f0fdf4',
    border: '#86efac',
    textClass: 'level-low',
    matrixBg: 'rgba(22, 163, 74, 0.60)',
  },
};

export const PROB_BANDS = [
  { label: 'Almost Certain', sublabel: 'P > 0.8', pMid: 0.85 },
  { label: 'Likely',         sublabel: '0.6 < P ≤ 0.8', pMid: 0.70 },
  { label: 'Possible',       sublabel: '0.4 < P ≤ 0.6', pMid: 0.50 },
  { label: 'Unlikely',       sublabel: '0.2 < P ≤ 0.4', pMid: 0.30 },
  { label: 'Rare',           sublabel: 'P ≤ 0.2', pMid: 0.15 },
];

export const IMPACT_LEVELS = [
  { label: 'Negligible', value: 1 },
  { label: 'Minor',      value: 2 },
  { label: 'Moderate',   value: 3 },
  { label: 'Major',      value: 4 },
  { label: 'Critical',   value: 5 },
];

export function classifyLevel(score: number): RiskLevel {
  if (score >= 4.0) return 'critical';
  if (score >= 2.5) return 'high';
  if (score >= 1.0) return 'medium';
  return 'low';
}

export function mapProbToRow(p: number): number {
  if (p > 0.8) return 0;
  if (p > 0.6) return 1;
  if (p > 0.4) return 2;
  if (p > 0.2) return 3;
  return 4;
}