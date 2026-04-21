// services/version.service.ts

import { Injectable, inject, NgZone } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject, interval, throwError } from 'rxjs';
import { map, catchError, share, switchMap, takeWhile, filter } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { SseService } from './sse.service';
import { ActiveVersion, AgentStatus, DecisionResponse, SSEEvent, UserStoryVersion, VersionState } from '../models/user_story.model';

@Injectable({
  providedIn: 'root'
})
export class VersionsService {
  private readonly http = inject(HttpClient);
  private readonly sseService = inject(SseService);
  private readonly ngZone = inject(NgZone);
  
  private readonly baseUrl = `${environment.apiUrl}/versions`;

  // Cache des versions actives
  private activeVersionsSubject = new BehaviorSubject<ActiveVersion[]>([]);
  public activeVersions$ = this.activeVersionsSubject.asObservable();

  // Événements SSE pour les versions
  private sseSubjects = new Map<string, BehaviorSubject<SSEEvent | null>>();

  constructor() {
    this.loadActiveVersions();
  }

  // ==============================
  // SSE CONNECTION
  // ==============================

  connectToVersionStream(versionId: string): Observable<SSEEvent> {
    if (this.sseSubjects.has(versionId)) {
      const subject = this.sseSubjects.get(versionId)!;
      return subject.asObservable().pipe(
        filter((event): event is SSEEvent => event !== null)
      );
    }

    const subject = new BehaviorSubject<SSEEvent | null>(null);
    this.sseSubjects.set(versionId, subject);

    const url = `${this.baseUrl}/${versionId}/stream`;
    
    this.sseService.connectToVersion(url, versionId).subscribe({
      next: (event) => {
        this.ngZone.run(() => {
          console.log(`[SSE] Version ${versionId} event:`, event.type);
          subject.next(event);
          
          if (event.type === 'completed' || event.type === 'failed') {
            setTimeout(() => {
              this.disconnectFromVersionStream(versionId);
            }, 5000);
          }
        });
      },
      error: (err) => {
        console.error(`[SSE] Error for version ${versionId}:`, err);
        subject.error(err);
        this.disconnectFromVersionStream(versionId);
      },
      complete: () => {
        console.log(`[SSE] Stream completed for version ${versionId}`);
        subject.complete();
        this.disconnectFromVersionStream(versionId);
      }
    });

    return subject.asObservable().pipe(
      filter((event): event is SSEEvent => event !== null),
      share()
    );
  }

  disconnectFromVersionStream(versionId: string): void {
    const subject = this.sseSubjects.get(versionId);
    if (subject) {
      subject.complete();
      this.sseSubjects.delete(versionId);
    }
    this.sseService.disconnect(versionId);
  }

  disconnectAllStreams(): void {
    this.sseSubjects.forEach((_, versionId) => {
      this.disconnectFromVersionStream(versionId);
    });
    this.sseService.disconnectAll();
  }

  isVersionConnected(versionId: string): boolean {
    return this.sseSubjects.has(versionId) && this.sseService.isConnected(versionId);
  }

  // ==============================
  // VERSION CRUD
  // ==============================

  getVersion(versionId: string): Observable<VersionState> {
    return this.http.get<VersionState>(`${this.baseUrl}/${versionId}`)
      .pipe(catchError(this.handleError));
  }

  getActiveVersions(): Observable<ActiveVersion[]> {
    return this.http.get<ActiveVersion[]>(`${this.baseUrl}/active/list`)
      .pipe(catchError(this.handleError));
  }

  loadActiveVersions(): void {
    this.getActiveVersions().subscribe({
      next: (versions) => this.activeVersionsSubject.next(versions),
      error: (err) => console.error('Failed to load active versions:', err)
    });
  }

  startVersion(storyId: string, reset: boolean = false): Observable<{ version_id: string; status: string; message: string }> {
    return this.http.post<{ version_id: string; status: string; message: string }>(
      `${this.baseUrl}/start/${storyId}`,
      { reset }
    ).pipe(catchError(this.handleError));
  }

  getStoryVersions(storyId: string, limit: number = 50, status?: AgentStatus): Observable<UserStoryVersion[]> {
    let url = `${this.baseUrl}/story/${storyId}?limit=${limit}`;
    if (status) {
      url += `&status=${status}`;
    }
    return this.http.get<UserStoryVersion[]>(url)
      .pipe(catchError(this.handleError));
  }

  getLatestVersionByIssueKey(issueKey: string): Observable<UserStoryVersion> {
    return this.http.get<UserStoryVersion>(`${this.baseUrl}/latest/${issueKey}`)
      .pipe(catchError(this.handleError));
  }

  getVersionsByIssueKeys(issueKeys: string[]): Observable<Record<string, any>> {
    return this.http.post<Record<string, any>>(`${this.baseUrl}/by-issue-keys`, issueKeys)
      .pipe(catchError(this.handleError));
  }

editVersion(versionId: string, improvedStory: string, acceptanceCriteria: string[]): Observable<any> {
  return this.http.put(`${this.baseUrl}/${versionId}/edit`, {
    improved_story: improvedStory,
    acceptance_criteria: acceptanceCriteria
  });
}

  /**
   * Vérifie si une version peut être modifiée
   * @param versionId ID de la version
   */
  canEditVersion(versionId: string): Observable<CanEditResponse> {
    return this.http.get<CanEditResponse>(
      `${this.baseUrl}/${versionId}/can-edit`
    ).pipe(catchError(this.handleError));
  }

  /**
   * Réinitialise le flag is_customized d'une version
   * @param versionId ID de la version
   */
  resetCustomization(versionId: string): Observable<ResetCustomizationResponse> {
    return this.http.post<ResetCustomizationResponse>(
      `${this.baseUrl}/${versionId}/reset-customization`,
      {}
    ).pipe(catchError(this.handleError));
  }

  // ==============================
  // DÉCISIONS
  // ==============================

  approveVersion(versionId: string): Observable<DecisionResponse> {
    return this.sendDecision(versionId, 'approve');
  }

  rejectKeepVersion(versionId: string): Observable<DecisionResponse> {
    return this.sendDecision(versionId, 'reject_keep');
  }

  rejectRelaunchVersion(versionId: string): Observable<DecisionResponse> {
    return this.sendDecision(versionId, 'relaunch');
  }

  sendDecision(versionId: string, decision: 'approve' | 'reject_keep' | 'relaunch'): Observable<DecisionResponse> {
    return this.http.post<DecisionResponse>(`${this.baseUrl}/${versionId}/decision`, { decision })
      .pipe(catchError(this.handleError));
  }

  // ==============================
  // POLLING (fallback)
  // ==============================

  pollVersionStatus(
    versionId: string,
    intervalMs: number = 2000,
    maxAttempts: number = 150
  ): Observable<VersionState> {
    let attempts = 0;
    
    return interval(intervalMs).pipe(
      switchMap(() => this.getVersion(versionId)),
      takeWhile((state) => {
        attempts++;
        const isProcessing = state.agent_status === 'processing';
        const shouldContinue = isProcessing && attempts < maxAttempts;
        if (!shouldContinue && isProcessing) {
          console.warn(`Polling timeout for version ${versionId} after ${maxAttempts} attempts`);
        }
        return shouldContinue;
      }, true),
      filter(state => state.agent_status !== 'processing')
    );
  }

  // ==============================
  // UTILITAIRES
  // ==============================

  isProcessing(version: UserStoryVersion | VersionState): boolean {
    return version?.agent_status === 'processing';
  }

  isCompleted(version: UserStoryVersion | VersionState): boolean {
    return version?.agent_status === 'completed';
  }

  isFailed(version: UserStoryVersion | VersionState): boolean {
    return version?.agent_status === 'failed';
  }

  isCustomized(version: UserStoryVersion | VersionState): boolean {
    return version?.is_customized === true;
  }

  getScoreDelta(version: UserStoryVersion): number {
    if (version.initial_score !== undefined && version.final_score !== undefined) {
      return version.final_score - version.initial_score;
    }
    return 0;
  }

  getStatusLabel(status: AgentStatus): string {
    const labels: Record<AgentStatus, string> = {
      'processing': 'En cours',
      'completed': 'Terminé',
      'failed': 'Échoué',
      'idle': 'Inactif'
    };
    return labels[status] || status;
  }

  getStatusClass(status: AgentStatus): string {
    const classes: Record<AgentStatus, string> = {
      'processing': 'status-processing',
      'completed': 'status-completed',
      'failed': 'status-failed',
      'idle': 'status-idle'
    };
    return classes[status] || '';
  }

  private handleError(error: any): Observable<never> {
    console.error('VersionsService error:', error);
    return throwError(() => error);
  }
}

// ==============================
// INTERFACES
// ==============================

export interface EditVersionResponse {
  status: 'success' | 'no_change';
  message: string;
  version_id: string;
  is_customized: boolean;
  customized_at: string | null;
}

export interface CanEditResponse {
  can_edit: boolean;
  reason: string | null;
  is_approved: boolean;
  is_customized: boolean;
}

export interface ResetCustomizationResponse {
  status: 'success' | 'no_change';
  message: string;
  version_id: string;
  is_customized: boolean;
  customized_at: string | null;
}