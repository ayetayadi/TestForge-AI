export type RiskLevel = 'critical' | 'high' | 'medium' | 'low';

export interface Risk {
  id: string;
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
   source?: 'ml' | 'ml_low_confidence' |'llm_fallback' | 'rules_fallback' | 'default' | 'human_modified';
  source_version_id?: string;
  source_story_text?: string;
  source_acceptance_criteria?: string;
  ml_confidence?: number;              
  modified_by?: string;          
  modified_at?: string;               
  original_probability?: number;       
  original_impact?: number;          
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
  { label: 'Almost Certain', sublabel: 'P = 5', pMid: 5 },
  { label: 'Likely',         sublabel: 'P = 4', pMid: 4 },
  { label: 'Possible',       sublabel: 'P = 3', pMid: 3 },
  { label: 'Unlikely',       sublabel: 'P = 2', pMid: 2 },
  { label: 'Rare',           sublabel: 'P = 1', pMid: 1 },
];

export const IMPACT_LEVELS = [
  { label: 'Negligible', value: 1 },
  { label: 'Minor',      value: 2 },
  { label: 'Moderate',   value: 3 },
  { label: 'Major',      value: 4 },
  { label: 'Critical',   value: 5 },
];

export function classifyLevel(score: number): RiskLevel {
  if (score >= 20) return 'critical';
  if (score >= 12) return 'high';
  if (score >= 6) return 'medium';
  return 'low';
}

export function mapProbToRow(p: number): number {
  return 5 - p;  // P=5 → row 0, P=1 → row 4
}