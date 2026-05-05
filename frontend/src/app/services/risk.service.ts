import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from 'src/environments/environment';
import { Risk, RiskLevel, RiskSummary } from '../models/risk.model';

// ============================================================
// REQUEST INTERFACES
// ============================================================

export interface AnalyzeRequest {
  story: string;
  acceptance_criteria?: string[];
  user_story_id?: string;
  issue_key?: string;
  test_plan_id?: string;
}

export interface BatchAnalysisRequest {
  project_id: string;
  stories: AnalyzeRequest[];
  test_plan_id?: string;
  concurrency?: number;
}

export interface ProjectAnalysisRequest {
  project_id: string;
  limit?: number;
  epic_keys?: string[];
  sprint_ids?: string[];
  jira_priorities?: string[];
  min_story_points?: number;
  use_approved_version_only?: boolean;
  force_reanalyze?: boolean;
}

export interface AnalyzeProjectResponse {
  submitted: number;
  project_id: string;
  job_ids: string[];
  priority_breakdown?: Record<string, number>;
  already_analyzed?: number;
  filters_applied?: string[];
  message: string;
}

export interface PendingCountResponse {
  total_stories: number;
  analyzed_stories: number;
  pending_stories: number;
  completion_percentage: number;
  priority_breakdown: Record<string, number>;
  has_pending: boolean;
  filters_applied: Record<string, any>;
}

export interface HumanCorrectionRequest {
  probability: number;  // 1-5
  impact: number;       // 1-5
  comment?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

// ============================================================
// SERVICE
// ============================================================

@Injectable({ providedIn: 'root' })
export class RiskService {
  private http = inject(HttpClient);
  private risksUrl = `${environment.apiUrl}/risks`;

  // ============================================================
  // AI-POWERED ANALYSIS
  // ============================================================

  /** Analyze all matching stories in a project (async via workers) */
  analyzeProjectWithFilters(request: ProjectAnalysisRequest): Observable<AnalyzeProjectResponse> {
    return this.http.post<AnalyzeProjectResponse>(
      `${this.risksUrl}/analyze-project`, request
    );
  }

  /** Get count of stories pending analysis */
  getPendingCount(filters: {
    project_id: string;
    epic_keys?: string[];
    sprint_ids?: string[];
    jira_priorities?: string[];
    min_story_points?: number;
  }): Observable<PendingCountResponse> {
    let params = new HttpParams().set('project_id', filters.project_id);
    if (filters.epic_keys) params = params.set('epic_keys', filters.epic_keys.join(','));
    if (filters.sprint_ids) params = params.set('sprint_ids', filters.sprint_ids.join(','));
    if (filters.jira_priorities) params = params.set('jira_priorities', filters.jira_priorities.join(','));
    if (filters.min_story_points) params = params.set('min_story_points', filters.min_story_points.toString());
    
    return this.http.get<PendingCountResponse>(`${this.risksUrl}/pending-count`, { params });
  }

  /** Analyze a single user story synchronously */
  analyzeUserStory(request: AnalyzeRequest): Observable<Risk> {
    return this.http.post<Risk>(`${this.risksUrl}/analyze`, request);
  }

  /** Analyze multiple user stories in batch */
  analyzeBatch(request: BatchAnalysisRequest): Observable<any> {
    return this.http.post(`${this.risksUrl}/analyze/batch`, request);
  }

  // ============================================================
  // CREATE (Manual)
  // ============================================================

  /** Create a risk manually without LLM */
  createRiskManual(risk: Partial<Risk>): Observable<Risk> {
    return this.http.post<Risk>(`${this.risksUrl}/manual`, risk);
  }

  // ============================================================
  // READ - Single Risk
  // ============================================================

  /** Get a single risk by ID */
  getRiskById(riskId: string): Observable<Risk> {
    return this.http.get<Risk>(`${this.risksUrl}/${riskId}`);
  }

  // ============================================================
  // READ - By User Story
  // ============================================================

  /** Get all risks for a specific user story */
  getRisksByUserStory(userStoryId: string): Observable<Risk[]> {
    return this.http.get<Risk[]>(`${this.risksUrl}/user-story/${userStoryId}`);
  }

  // ============================================================
  // READ - By Project
  // ============================================================

  /** Get all risks for a project with optional filters */
  getRisksByProject(
    projectId: string,
    level?: RiskLevel,
    isAccepted?: boolean,
    isAiGenerated?: boolean
  ): Observable<Risk[]> {
    let params = new HttpParams();
    if (level) params = params.set('level', level);
    if (isAccepted !== undefined) params = params.set('is_accepted', isAccepted.toString());
    if (isAiGenerated !== undefined) params = params.set('is_ai_generated', isAiGenerated.toString());
    return this.http.get<Risk[]>(`${this.risksUrl}/project/${projectId}`, { params });
  }

  /** Get risk summary statistics for a project */
  getRiskSummaryByProject(projectId: string): Observable<RiskSummary> {
    return this.http.get<RiskSummary>(`${this.risksUrl}/project/${projectId}/summary`);
  }

  // ============================================================
  // READ - By Sprint
  // ============================================================

  /** Get all risks for a sprint */
  getRisksBySprint(
    projectId: string,
    sprint: string,
    level?: RiskLevel,
    isAccepted?: boolean
  ): Observable<Risk[]> {
    let params = new HttpParams();
    if (level) params = params.set('level', level);
    if (isAccepted !== undefined) params = params.set('is_accepted', isAccepted.toString());
    return this.http.get<Risk[]>(
      `${this.risksUrl}/project/${projectId}/sprint/${encodeURIComponent(sprint)}`,
      { params }
    );
  }

  /** Get risk summary for a sprint */
  getRiskSummaryBySprint(projectId: string, sprint: string): Observable<RiskSummary> {
    return this.http.get<RiskSummary>(
      `${this.risksUrl}/project/${projectId}/sprint/${encodeURIComponent(sprint)}/summary`
    );
  }

  // ============================================================
  // READ - By Epic
  // ============================================================

  /** Get all risks for an epic */
  getRisksByEpic(
    projectId: string,
    epicKey: string,
    level?: RiskLevel
  ): Observable<Risk[]> {
    let params = new HttpParams();
    if (level) params = params.set('level', level);
    return this.http.get<Risk[]>(
      `${this.risksUrl}/project/${projectId}/epic/${encodeURIComponent(epicKey)}`,
      { params }
    );
  }

  /** Get risk summary for an epic */
  getRiskSummaryByEpic(projectId: string, epicKey: string): Observable<RiskSummary> {
    return this.http.get<RiskSummary>(
      `${this.risksUrl}/project/${projectId}/epic/${encodeURIComponent(epicKey)}/summary`
    );
  }

  // ============================================================
  // READ - High Priority / Critical
  // ============================================================

  /** Get high priority risks (score ≥ minScore) */
  getHighPriorityRisks(projectId?: string, minScore: number = 12): Observable<Risk[]> {
    let params = new HttpParams().set('min_score', minScore.toString());
    if (projectId) params = params.set('project_id', projectId);
    return this.http.get<Risk[]>(`${this.risksUrl}/high-priority`, { params });
  }

  /** Get critical risks only (score ≥ 20) */
  getCriticalRisks(projectId?: string): Observable<Risk[]> {
    let params = new HttpParams();
    if (projectId) params = params.set('project_id', projectId);
    return this.http.get<Risk[]>(`${this.risksUrl}/critical`, { params });
  }

  // ============================================================
  // READ - List (Paginated)
  // ============================================================

  /** Get paginated list of risks with optional filters */
  listRisks(filters?: {
    project_id?: string;
    sprint?: string;
    epic_key?: string;
    user_story_id?: string;
    level?: RiskLevel;
    is_accepted?: boolean;
    source?: string;
    page?: number;
    page_size?: number;
  }): Observable<PaginatedResponse<Risk>> {
    let params = new HttpParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
          params = params.set(key, value.toString());
        }
      });
    }
    return this.http.get<PaginatedResponse<Risk>>(`${this.risksUrl}/list`, { params });
  }

  // ============================================================
  // READ - All (with filters)
  // ============================================================

  /** Get all risks with optional filters */
  getAllRisks(filters?: {
    project_id?: string;
    sprint?: string;
    epic_key?: string;
    level?: RiskLevel;
    is_accepted?: boolean;
    source?: 'llm' | 'original' | 'approved_version' | 'human_modified' | 'manual';
  }): Observable<Risk[]> {
    let params = new HttpParams();
    if (filters) {
      Object.entries(filters).forEach(([key, value]) => {
        if (value !== undefined && value !== null) {
          params = params.set(key, value.toString());
        }
      });
    }
    return this.http.get<Risk[]>(`${this.risksUrl}/all`, { params });
  }

  // ============================================================
  // UPDATE
  // ============================================================

  /** Update a risk (recomputes score if P or I changes) */
  updateRisk(riskId: string, updates: Partial<Risk>): Observable<Risk> {
    return this.http.patch<Risk>(`${this.risksUrl}/${riskId}`, updates);
  }

  /** Accept or reject a risk analysis */
  acceptRisk(riskId: string, accepted: boolean): Observable<Risk> {
    return this.http.patch<Risk>(
      `${this.risksUrl}/${riskId}/accept?accepted=${accepted}`, {}
    );
  }

  /** Update mitigation strategy */
  updateMitigation(riskId: string, mitigation: string): Observable<Risk> {
    return this.http.patch<Risk>(
      `${this.risksUrl}/${riskId}/mitigation`,
      { mitigation }
    );
  }

  /** Human correction of LLM-generated P and I */
  humanCorrectRisk(riskId: string, correction: HumanCorrectionRequest): Observable<Risk> {
    return this.http.patch<Risk>(
      `${this.risksUrl}/${riskId}/human-correct`,
      correction
    );
  }

  /** Re-analyze a risk with updated story */
  reanalyzeRisk(
    riskId: string,
    story: string,
    acceptanceCriteria: string[]
  ): Observable<Risk> {
    return this.http.post<Risk>(
      `${this.risksUrl}/${riskId}/reanalyze`,
      { story, acceptance_criteria: acceptanceCriteria }
    );
  }

  // ============================================================
  // DELETE
  // ============================================================

  /** Delete a single risk */
  deleteRisk(riskId: string): Observable<void> {
    return this.http.delete<void>(`${this.risksUrl}/${riskId}`);
  }

  /** Delete all risks for a project */
  deleteProjectRisks(projectId: string): Observable<void> {
    return this.http.delete<void>(`${this.risksUrl}/project/${projectId}`);
  }
}

// ============================================================
// STRATÉGIES D'ANALYSE (à ajouter APRÈS la classe RiskService)
// ============================================================

export class ProgressiveAnalysisStrategy {
  constructor(private riskService: RiskService) {}

  async analyzeProjectByEpics(
    projectId: string, 
    epicKeys: string[], 
    onProgress?: (current: number, total: number, epic: string) => void
  ): Promise<{ totalSubmitted: number; epicResults: any[] }> {
    const results = [];
    let totalSubmitted = 0;

    for (let i = 0; i < epicKeys.length; i++) {
      const epic = epicKeys[i];
      
      if (onProgress) {
        onProgress(i + 1, epicKeys.length, epic);
      }

      const result = await this.riskService.analyzeProjectWithFilters({
        project_id: projectId,
        epic_keys: [epic],
        limit: 20,
        force_reanalyze: false
      }).toPromise();

      results.push({ epic, result });
      totalSubmitted += result?.submitted || 0;

      if (i < epicKeys.length - 1) {
        await this.delay(5000);
      }
    }

    return { totalSubmitted, epicResults: results };
  }

  async analyzeProjectByPriority(
    projectId: string,
    priorities: string[] = ['Highest', 'High', 'Medium', 'Low'],
    onProgress?: (current: number, total: number, priority: string) => void
  ): Promise<{ totalSubmitted: number }> {
    let totalSubmitted = 0;

    for (let i = 0; i < priorities.length; i++) {
      const priority = priorities[i];
      
      if (onProgress) {
        onProgress(i + 1, priorities.length, priority);
      }

      const result = await this.riskService.analyzeProjectWithFilters({
        project_id: projectId,
        jira_priorities: [priority],
        limit: 15,
        force_reanalyze: false
      }).toPromise();

      totalSubmitted += result?.submitted || 0;
      await this.delay(3000);
    }

    return { totalSubmitted };
  }

  async analyzeProjectBySprints(
    projectId: string,
    sprintIds: string[],
    onProgress?: (current: number, total: number, sprintId: string) => void
  ): Promise<{ totalSubmitted: number }> {
    let totalSubmitted = 0;

    for (let i = 0; i < sprintIds.length; i++) {
      const sprintId = sprintIds[i];
      
      if (onProgress) {
        onProgress(i + 1, sprintIds.length, sprintId);
      }

      const result = await this.riskService.analyzeProjectWithFilters({
        project_id: projectId,
        sprint_ids: [sprintId],
        limit: 20,
        force_reanalyze: false
      }).toPromise();

      totalSubmitted += result?.submitted || 0;
      await this.delay(4000);
    }

    return { totalSubmitted };
  }

  async analyzeHighValueStories(
    projectId: string,
    minPoints: number = 8
  ): Promise<any> {
    return this.riskService.analyzeProjectWithFilters({
      project_id: projectId,
      min_story_points: minPoints,
      limit: 20,
      force_reanalyze: false
    }).toPromise();
  }

  private delay(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

export class RiskAnalysisValidator {
  static async canAnalyzeSafely(
    riskService: RiskService, 
    projectId: string
  ): Promise<{ safe: boolean; reason?: string; estimatedTime?: number }> {
    return new Promise((resolve) => {
      riskService.getPendingCount({ project_id: projectId }).subscribe({
        next: (status) => {
          if (status.pending_stories === 0) {
            resolve({ safe: true, reason: 'No pending analyses' });
          } else if (status.pending_stories > 50) {
            resolve({ 
              safe: false, 
              reason: `Too many pending analyses (${status.pending_stories}). Use filters to analyze in smaller batches.`,
              estimatedTime: Math.round(status.pending_stories * 3 / 60)
            });
          } else {
            resolve({ 
              safe: true,
              estimatedTime: Math.round(status.pending_stories * 3 / 60)
            });
          }
        },
        error: () => {
          resolve({ safe: false, reason: 'Unable to check analysis status' });
        }
      });
    });
  }

  static getRecommendedBatches(totalStories: number): number {
    const BATCH_SIZE = 20;
    return Math.ceil(totalStories / BATCH_SIZE);
  }
}