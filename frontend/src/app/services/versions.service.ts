// services/version.service.ts
import { Injectable, inject, NgZone } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, BehaviorSubject, interval, throwError } from 'rxjs';
import { map, catchError, share, switchMap, takeWhile, filter } from 'rxjs/operators';
import { environment } from '../../environments/environment';
import { SseService } from './sse.service';
import { ActiveVersion, AgentStatus, DecisionResponse, SSEEvent, UserStoryVersion, VersionState } from '../models';

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

  /**
   * Se connecte au flux SSE d'une version
   */
  connectToVersionStream(versionId: string): Observable<SSEEvent> {
    // Vérifier si déjà connecté
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
          
          // Si événement terminal, fermer après 5 secondes
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

  /**
   * Se déconnecte du flux SSE d'une version
   */
  disconnectFromVersionStream(versionId: string): void {
    const subject = this.sseSubjects.get(versionId);
    if (subject) {
      subject.complete();
      this.sseSubjects.delete(versionId);
    }
    this.sseService.disconnect(versionId);
  }

  /**
   * Se déconnecte de tous les flux SSE
   */
  disconnectAllStreams(): void {
    this.sseSubjects.forEach((_, versionId) => {
      this.disconnectFromVersionStream(versionId);
    });
    this.sseService.disconnectAll();
  }

  /**
   * Vérifie si une version est connectée au SSE
   */
  isVersionConnected(versionId: string): boolean {
    return this.sseSubjects.has(versionId) && this.sseService.isConnected(versionId);
  }

  // ==============================
  // VERSION CRUD (garde vos méthodes existantes)
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
    return this.sendDecision(versionId, 'reject_relaunch');
  }

  sendDecision(versionId: string, decision: 'approve' | 'reject_keep' | 'reject_relaunch'): Observable<DecisionResponse> {
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