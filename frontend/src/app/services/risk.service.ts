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
  jira_priority?: string;
  story_points?: number;
  components?: string[];
  labels?: string[];
  epic?: string;
  issue_key?: string;
}

export interface BatchAnalysisRequest {
  project_id: string;
  stories: AnalyzeRequest[];       
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
  message: string;
}

export interface RateLimitStatus {
  pending_analyses: number;
  estimated_time_minutes: number;
  rate_limit_tpm: number;
  recommended_batch_size: number;
  message: string;
}

// ============================================================
// SERVICE
// ============================================================

@Injectable({ providedIn: 'root' })
export class RiskService {
  private http = inject(HttpClient);
  private risksUrl = `${environment.apiUrl}/risks`;
  private projectsUrl = `${environment.apiUrl}/projects`;

  // ── All risks (with enriched filters) ────────────────────
  getAllRisks(filters?: {
    project_id?: string;
    sprint?: string;
    epic_key?: string;
    level?: RiskLevel;
    is_accepted?: boolean;
    source?: 'original' | 'approved_version';
  }): Observable<Risk[]> {
    let params = new HttpParams();
    if (filters) {
      if (filters.project_id) params = params.set('project_id', filters.project_id);
      if (filters.sprint) params = params.set('sprint', filters.sprint);
      if (filters.epic_key) params = params.set('epic_key', filters.epic_key);
      if (filters.level) params = params.set('level', filters.level);
      if (filters.is_accepted !== undefined) params = params.set('is_accepted', filters.is_accepted.toString());
      if (filters.source) params = params.set('source', filters.source);
    }
    return this.http.get<Risk[]>(`${this.risksUrl}/all`, { params });
  }

  // ── By project (primary) ──────────────────────────────────
  getRisksByProject(projectId: string, level?: RiskLevel): Observable<Risk[]> {
    let params = new HttpParams();
    if (level) params = params.set('level', level);
    return this.http.get<Risk[]>(`${this.risksUrl}/project/${projectId}`, { params });
  }

  getRiskSummaryByProject(projectId: string): Observable<RiskSummary> {
    return this.http.get<RiskSummary>(`${this.risksUrl}/project/${projectId}/summary`);
  }

  // ── By sprint (NEW) ──────────────────────────────────────
  getRisksBySprint(projectId: string, sprint: string, level?: RiskLevel): Observable<Risk[]> {
    let params = new HttpParams();
    if (level) params = params.set('level', level);
    return this.http.get<Risk[]>(`${this.risksUrl}/project/${projectId}/sprint/${sprint}`, { params });
  }

  getRiskSummaryBySprint(projectId: string, sprint: string): Observable<RiskSummary> {
    return this.http.get<RiskSummary>(`${this.risksUrl}/project/${projectId}/sprint/${sprint}/summary`);
  }

  // ── By epic (NEW) ────────────────────────────────────────
  getRisksByEpic(projectId: string, epicKey: string, level?: RiskLevel): Observable<Risk[]> {
    let params = new HttpParams();
    if (level) params = params.set('level', level);
    return this.http.get<Risk[]>(`${this.risksUrl}/project/${projectId}/epic/${epicKey}`, { params });
  }

  // ── Analyze project with filters ─────────────────────────
  analyzeProjectWithFilters(request: ProjectAnalysisRequest): Observable<AnalyzeProjectResponse> {
    return this.http.post<AnalyzeProjectResponse>(`${this.risksUrl}/analyze-project`, request);
  }

  getPendingCount(filters: {
    project_id: string;
    epic_keys?: string[];
    sprint_ids?: string[];
    jira_priorities?: string[];
    min_story_points?: number;
  }): Observable<{
    total_stories: number;
    analyzed_stories: number;
    pending_stories: number;
    priority_breakdown: Record<string, number>;
    has_pending: boolean;
  }> {
    let params = new HttpParams().set('project_id', filters.project_id);
    
    if (filters.epic_keys?.length) {
      params = params.set('epic_keys', filters.epic_keys.join(','));
    }
    if (filters.sprint_ids?.length) {
      params = params.set('sprint_ids', filters.sprint_ids.join(','));
    }
    if (filters.jira_priorities?.length) {
      params = params.set('jira_priorities', filters.jira_priorities.join(','));
    }
    if (filters.min_story_points) {
      params = params.set('min_story_points', filters.min_story_points.toString());
    }
    
    return this.http.get<{
      total_stories: number;
      analyzed_stories: number;
      pending_stories: number;
      priority_breakdown: Record<string, number>;
      has_pending: boolean;
    }>(`${this.risksUrl}/pending-count`, { params });
  }

  // ── Batch Analysis ────────────────────────────────────────
  analyzeBatch(request: BatchAnalysisRequest): Observable<any> {
    return this.http.post(`${this.risksUrl}/analyze/batch`, request);
  }

  // ── Rate Limit Status ─────────────────────────────────────
  getRateLimitStatus(): Observable<RateLimitStatus> {
    return this.http.get<RateLimitStatus>(`${this.risksUrl}/rate-limit-status`);
  }

  // ── High Priority Risks ───────────────────────────────────
  getHighPriorityRisks(projectId?: string, minScore: number = 2.5): Observable<Risk[]> {
    let params = new HttpParams().set('min_score', minScore.toString());
    if (projectId) params = params.set('project_id', projectId);
    return this.http.get<Risk[]>(`${this.risksUrl}/high-priority`, { params });
  }

  getRiskById(riskId: string): Observable<Risk> {
    return this.http.get<Risk>(`${this.risksUrl}/${riskId}`);
  }

  // ── User Story specific ───────────────────────────────────
  getRisksByUserStory(userStoryId: string): Observable<Risk[]> {
    return this.http.get<Risk[]>(`${this.risksUrl}/user-story/${userStoryId}`);
  }

  // ── Actions ───────────────────────────────────────────────
  analyzeUserStory(projectId: string, req: AnalyzeRequest): Observable<Risk> {
    return this.http.post<Risk>(`${this.risksUrl}/analyze?project_id=${projectId}`, req);
  }

  acceptRisk(riskId: string, accepted: boolean): Observable<Risk> {
    return this.http.patch<Risk>(`${this.risksUrl}/${riskId}/accept?accepted=${accepted}`, {});
  }

  updateMitigation(riskId: string, mitigation: string): Observable<Risk> {
    return this.http.patch<Risk>(`${this.risksUrl}/${riskId}/mitigation`, { mitigation });
  }

  reanalyzeRisk(riskId: string, story: string, acceptanceCriteria: string[]): Observable<Risk> {
    return this.http.post<Risk>(`${this.risksUrl}/${riskId}/reanalyze`, {
      story,
      acceptance_criteria: acceptanceCriteria
    });
  }

  updateRisk(riskId: string, updates: Partial<Risk>): Observable<Risk> {
    return this.http.patch<Risk>(`${this.risksUrl}/${riskId}`, updates);
  }

  deleteRisk(riskId: string): Observable<void> {
    return this.http.delete<void>(`${this.risksUrl}/${riskId}`);
  }

  deleteProjectRisks(projectId: string): Observable<void> {
    return this.http.delete<void>(`${this.risksUrl}/project/${projectId}`);
  }
}

// ============================================================
// STRATÉGIES D'ANALYSE (inchangées - déjà bonnes)
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
  static async canAnalyzeSafely(riskService: RiskService): Promise<{ safe: boolean; reason?: string; estimatedTime?: number }> {
    const status = await riskService.getRateLimitStatus().toPromise();
    
    if (!status) {
      return { safe: false, reason: 'Unable to get rate limit status' };
    }

    if (status.pending_analyses === 0) {
      return { safe: true, reason: 'No pending analyses' };
    }

    if (status.pending_analyses > 50) {
      return { 
        safe: false, 
        reason: `Too many pending analyses (${status.pending_analyses}). Use filters to analyze in smaller batches.`,
        estimatedTime: status.estimated_time_minutes
      };
    }

    return { 
      safe: true,
      estimatedTime: status.estimated_time_minutes
    };
  }

  static getRecommendedBatches(totalStories: number): number {
    const BATCH_SIZE = 20;
    return Math.ceil(totalStories / BATCH_SIZE);
  }
}