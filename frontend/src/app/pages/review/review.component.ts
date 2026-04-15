// ============================================================
// src/app/pages/review/review.component.ts (CORRIGÉ)
// ============================================================

import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { JobsService, ToastService, PipelineService, SseService } from '../../services';
import { DecisionChoice, JobState, SSEEvent, TraceEntry, UserStoryVersion } from '../../models';
import { environment } from '../../../environments/environment';
import { Subscription } from 'rxjs';

@Component({
  selector: 'app-review',
  standalone: true,
  imports: [CommonModule, SpinnerComponent, ScoreBadgeComponent],
  templateUrl: './review.component.html',
  styleUrls: ['./review.component.scss'],
})
export class ReviewComponent implements OnInit, OnDestroy {

  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private jobsService = inject(JobsService);
  private toastService = inject(ToastService);
  private pipelineService = inject(PipelineService);
  private sseService = inject(SseService);

  // Current job being viewed
  jobId = '';

  // Job state from API
  state = signal<JobState | null>(null);

  // All versions for this story
  allVersions = signal<UserStoryVersion[]>([]);

  // Currently viewing version (can switch between versions)
  viewingVersionId = signal<string | null>(null);

  // UI states
  loading = signal(true);
  error = signal<string | null>(null);
  submitting = signal(false);
  decisionMade = signal(false);

  // Relaunch states
  relaunching = signal(false);
  relaunchPhase = signal<string>('');

  // ============================================================
  // ❌ SUPPRIMER: step signal (plus utilisé)
  // step = signal<'analysis' | 'refinement' | 'done' | 'idle'>('idle');

  // ✅ REMPLACER PAR:
  processingStep = signal<'processing' | 'done'>('done');

  // Navigation context
  private navProjectId: string | null = null;
  private navProjectName: string | null = null;
  private issueKey: string | null = null;

  // SSE subscription
  private sseSubscription: Subscription | null = null;

  // ─────────────────────────────────────────────
  // COMPUTED
  // ─────────────────────────────────────────────

  /**
   * Version actuellement affichée
   */
  currentVersion = computed(() => {
    const versions = this.allVersions();
    const viewingId = this.viewingVersionId();
    const state = this.state();
    
    if (viewingId) {
      const found = versions.find(v => v.id === viewingId);
      if (found) return found;
    }
    
    if (state?.version_id && versions.length > 0) {
      const found = versions.find(v => v.id === state.version_id);
      if (found) return found;
    }
    
    if (versions.length > 0) {
      return [...versions].sort((a,b) => (a.iteration ?? 0) - (b.iteration ?? 0)).at(-1);
    }
    
    if (state && state.improved_story && state.version_id) {
      return {
        id: state.version_id,
        user_story_id: state.user_story_id || '',
        job_id: state.job_id,
        improved_story: state.improved_story,
        generated_acceptance_criteria: state.generated_acceptance_criteria || [],
        initial_score: state.initial_score || 0,
        final_score: state.final_score || 0,
        iteration: state.iteration || 0,
        decision_status: 'pending',
        testability_score: state.testability_score,
        is_testable: state.is_testable,
        testability_issues: state.testability_issues || []
      } as UserStoryVersion;
    }
    
    return null;
  });

  /**
   * Vérifie si on regarde la dernière version (la plus récente)
   */
  isViewingLatestVersion = computed(() => {
    const versions = this.allVersions();
    
    if (versions.length === 0) return true;
    
    const current = this.currentVersion();
    if (!current) return true;
    
    const latestVersion = versions[versions.length - 1];
    return current.id === latestVersion.id;
  });

  /**
   * Retourne le numéro de la version actuelle
   */
  getCurrentVersionNumber = computed(() => {
    const versions = this.allVersions();
    const current = this.currentVersion();
    
    if (!current || versions.length === 0) return 1;
    
    const index = versions.findIndex(v => v.id === current.id);
    return index >= 0 ? index + 1 : versions.length;
  });

  /**
   * Vérifie si la story a une décision FINALE
   */
  hasFinalDecision = computed(() => {
    const s = this.state();
    const decision = s?.decision_status;
    return decision === 'approved';
  });

  /**
   * Vérifie si on peut prendre une décision
   */
  canMakeDecision = computed(() => {
    const s = this.state();
    
    if (!s || s.status !== 'completed') return false;
    if (this.relaunching()) return false;
    if (this.decisionMade()) return false;

    const versionId = this.currentVersion()?.id;
    if (!versionId) return false;  
    return true;
  });

  /**
   * Meilleure version (score le plus élevé)
   */
  bestVersion = computed(() => {
    const versions = this.allVersions();
    if (!versions.length) return null;

    return versions.reduce((best, v) =>
      (v.final_score || 0) > (best.final_score || 0) ? v : best
    );
  });

  isBest(version: UserStoryVersion): boolean {
    return this.bestVersion()?.id === version.id;
  }

  /**
   * Version sélectionnée (approuvée)
   */
  selectedVersion = computed(() => {
    const versions = this.allVersions();
    return versions.find(v => v.decision_status === 'approved') ?? null;
  });

  /**
   * Nombre de versions
   */
  versionCount = computed(() => this.allVersions().length);

  // ─────────────────────────────────────────────
  // LIFECYCLE
  // ─────────────────────────────────────────────

  ngOnInit(): void {
    this.route.queryParams.subscribe(params => {
      this.navProjectId = params['projectId'] ?? null;
      this.navProjectName = params['projectName'] ?? null;
      this.issueKey = params['issueKey'] ?? null;
    });

    this.route.params.subscribe(params => {
      const jobId = params['jobId'];

      if (!jobId) {
        this.error.set("Missing jobId");
        this.loading.set(false);
        return;
      }

      this.jobId = jobId;
      this.resetState();
      this.loadJob(this.jobId);
    });
  }

  ngOnDestroy(): void {
    this.cleanupSSE();
  }

  private resetState(): void {
    this.decisionMade.set(false);
    this.relaunching.set(false);
    this.relaunchPhase.set('');
    this.processingStep.set('done');  // ✅ Mise à jour
    this.viewingVersionId.set(null);
    this.allVersions.set([]);
  }

  // ─────────────────────────────────────────────
  // SSE MANAGEMENT
  // ─────────────────────────────────────────────

  private cleanupSSE(): void {
    if (this.sseSubscription) {
      this.sseSubscription.unsubscribe();
      this.sseSubscription = null;
    }
    if (this.jobId) {
      this.sseService.disconnect(this.jobId);
    }
  }

  private listenToStream(jobId: string): void {
    if (this.sseSubscription) return;

    const url = `${environment.apiUrl}/jobs/${jobId}/stream`;
    console.log("[SSE CONNECT]", jobId);

    this.sseSubscription = this.sseService.connect(url, jobId).subscribe({
      next: (event: SSEEvent) => {
        console.log("[SSE EVENT]", event.type, event.data);

        // ============================================================
        // ✅ SIMPLIFIÉ: Juste 3 events
        // ============================================================
        switch (event.type) {
          case 'processing':
            // ✅ Agent tourne
            this.processingStep.set('processing');
            console.log("[SSE] Agent processing:", event.data?.message);
            break;

          case 'completed':
            // ✅ Complété
            this.cleanupSSE();
            this.processingStep.set('done');
            this.loadJob(jobId);
            break;

          case 'failed':
            // ✅ Erreur
            this.cleanupSSE();
            this.processingStep.set('done');
            this.error.set('Pipeline failed');
            break;
        }
      },
      error: (err) => {
        console.error("[SSE ERROR]", err);
        this.cleanupSSE();
      }
    });
  }

  // ─────────────────────────────────────────────
  // LOAD JOB & VERSIONS
  // ─────────────────────────────────────────────

  loadJob(jobId: string): void {
    this.loading.set(true);
    this.error.set(null);

    this.jobsService.getJob(jobId).subscribe({
      next: (jobState) => {
        console.log("[LOAD JOB] Full response:", JSON.stringify(jobState, null, 2));

        if (jobState.status === 'not_found') {
          this.error.set('Job not found');
          this.loading.set(false);
          return;
        }

        this.state.set(jobState);

        if (!this.issueKey && jobState.issue_key) {
          this.issueKey = jobState.issue_key;
        }

        if (jobState.user_story_id) {
          this.loadVersions(jobState.user_story_id);
        } else {
          this.loading.set(false);
        }

        // ============================================================
        // ✅ SIMPLIFIÉ: Juste checking processing vs completed/failed
        // ============================================================
        const status = jobState.status;

        if (status === 'processing') {
          // ✅ Agent tourne
          this.processingStep.set('processing');
          this.listenToStream(jobId);
        } else {
          // ✅ Complété ou failed
          this.processingStep.set('done');
        }

        if (!this.navProjectId && jobState.project_id) {
          this.navProjectId = jobState.project_id;
        }
        if (!this.navProjectName && jobState.project_name) {
          this.navProjectName = jobState.project_name;
        }
      },
      error: (err) => {
        this.error.set(err.message || 'Failed to load job');
        this.loading.set(false);
      },
    });
  }

  /**
   * Charge toutes les versions d'une story
   */
  private loadVersions(storyId: string): void {
    fetch(`${environment.apiUrl}/user-stories/${storyId}/versions`)
      .then(res => {
        if (!res.ok) {
          console.warn(`[VERSIONS] HTTP ${res.status}`);
          return [];
        }
        return res.json();
      })
      .then((versions: any) => {
        console.log("[VERSIONS RAW]", versions);
        const data = Array.isArray(versions)
          ? versions
          : versions?.data || versions?.versions || [];
        console.log("[VERSIONS FIXED]", data);
        this.allVersions.set(data);
        this.loading.set(false);
      })
      .catch(err => {
        console.error("[VERSIONS ERROR]", err);
        this.allVersions.set([]);
        this.loading.set(false);
      });
  }

  // ─────────────────────────────────────────────
  // VERSION NAVIGATION
  // ─────────────────────────────────────────────

  viewVersion(version: UserStoryVersion): void {
    this.viewingVersionId.set(version.id);
  }

  viewLatestVersion(): void {
    const versions = this.allVersions();
    if (versions.length > 0) {
      const latest = versions[versions.length - 1];
      this.viewingVersionId.set(latest.id);
    } else {
      this.viewingVersionId.set(null);
    }
  }

  isViewing(version: UserStoryVersion): boolean {
    return this.currentVersion()?.id === version.id;
  }

  isLatest(index: number): boolean {
    return index === this.allVersions().length - 1;
  }

  // ─────────────────────────────────────────────
  // GETTERS - Story & Version Info
  // ─────────────────────────────────────────────

  getIssueKey(): string {
    return this.state()?.issue_key || this.state()?.jira_id || this.issueKey || 'Unknown';
  }

  getOriginalScore(): number {
    return this.currentVersion()?.initial_score ?? this.state()?.initial_score ?? 0;
  }

  getFinalScore(): number {
    return this.currentVersion()?.final_score ?? this.state()?.final_score ?? 0;
  }

  getDelta(): number {
    const v = this.currentVersion();
    if (!v) return 0;
    return (v.final_score ?? 0) - (v.initial_score ?? 0);
  }

  getIteration(): number {
    return this.currentVersion()?.iteration ?? this.state()?.iteration ?? 0;
  }

  getOriginalStory(): string {
    const s = this.state();
    return s?.initial_story || s?.raw_story || '';
  }

  getImprovedStory(): string {
    return this.currentVersion()?.improved_story ?? this.state()?.improved_story ?? '';
  }

  getOriginalAC(): string[] {
    return this.parseAc(this.state()?.existing_ac);
  }

  getImprovedAC(): string[] {
    const version = this.currentVersion();
    if (version?.generated_acceptance_criteria) {
      return version.generated_acceptance_criteria;
    }
    return this.parseAc(this.state()?.generated_acceptance_criteria);
  }

  private parseAc(ac: string[] | string | undefined | null): string[] {
    if (!ac) return [];

    if (Array.isArray(ac)) {
      return ac.filter(item => item && String(item).trim());
    }

    if (typeof ac === 'string') {
      try {
        const parsed = JSON.parse(ac);
        if (Array.isArray(parsed)) return parsed;
      } catch {}

      return ac
        .split('\n')
        .map((x: string) => x.trim())
        .filter(Boolean);
    }

    return [];
  }

  // ─────────────────────────────────────────────
  // TRACE & HISTORY
  // ─────────────────────────────────────────────

  getScoreExplanation(): string | null {
    const trace = this.state()?.trace || [];

    for (let i = trace.length - 1; i >= 0; i--) {
      if (trace[i]?.data?.justification) {
        return trace[i].data!.justification!;
      }
    }

    return null;
  }

  getTrace(): TraceEntry[] {
    return this.state()?.trace || [];
  }

  getTraceScore(entry: TraceEntry): number | null {
    if (entry?.data?.final !== undefined) return entry.data.final;
    if (entry?.data?.current_score !== undefined) return entry.data.current_score;
    return null;
  }

  getTestabilityScore(): number | null {
    return (
      this.currentVersion()?.testability_score ??
      this.state()?.testability_score ??
      null
    );
  }

  isTestable(): boolean | null {
    return (
      this.currentVersion()?.is_testable ??
      this.state()?.is_testable ??
      null
    );
  }

  getTestabilityIssues(): string[] {
    return (
      this.currentVersion()?.testability_issues ??
      this.state()?.testability_issues ??
      []
    );
  }

  // ─────────────────────────────────────────────
  // DECISION
  // ─────────────────────────────────────────────

  submitDecision(choice: DecisionChoice): void {
    if (!this.jobId || this.submitting() || !this.canMakeDecision()) return;

    const versionId = this.currentVersion()?.id;
    console.log("🚨 VERSION SENT:", versionId);

    if (!versionId) {
      this.toastService.error("No valid version found. Please wait.");
      return;
    }

    this.submitting.set(true);
    this.jobsService.sendDecision(this.jobId, choice, versionId).subscribe({
      next: (res) => {
        this.submitting.set(false);

        if (res.status === 'error') {
          this.toastService.error(res.message || 'Decision failed');
          return;
        }

        this.decisionMade.set(true);

        switch (choice) {
          case 'approve':
            this.toastService.success('Version approved successfully');
            this.navigateToStories();
            break;

          case 'reject_keep':
            this.toastService.info('Original version kept (AI suggestion rejected)');
            this.navigateToStories();
            break;

          case 'reject_relaunch':
            this.handleRelaunch(res);
            break;
        }
      },
      error: (err) => {
        this.submitting.set(false);
        this.toastService.error('Decision failed');
        console.error('[DECISION ERROR]', err);
      }
    });
  }

  // ─────────────────────────────────────────────
  // RELAUNCH
  // ─────────────────────────────────────────────

  private handleRelaunch(res: any): void {
    const newJobId = res.job_id;

    if (!newJobId) {
      this.toastService.error('Relaunch failed: no job_id');
      this.navigateToStories();
      return;
    }

    this.relaunching.set(true);
    this.relaunchPhase.set('Processing...');

    this.jobId = newJobId;
    this.connectRelaunchSSE(newJobId);
    this.loadJob(newJobId);
  }

  private connectRelaunchSSE(newJobId: string): void {
    this.cleanupSSE();

    const url = `${environment.apiUrl}/jobs/${newJobId}/stream`;

    this.sseSubscription = this.sseService.connect(url, newJobId).subscribe({
      next: (event: SSEEvent) => {
        console.log('[RELAUNCH SSE]', event.type, event.data);

        // ============================================================
        // ✅ SIMPLIFIÉ: Juste processing/completed/failed
        // ============================================================
        switch (event.type) {
          case 'processing':
            // ✅ Juste "Processing..." sans détails de phase
            this.relaunchPhase.set('Processing...');
            break;

          case 'completed':
            this.cleanupSSE();
            this.relaunching.set(false);
          
            const hasNewVersion = event.data?.has_new_version;
          
            if (hasNewVersion) {
              this.toastService.success('New version created');
            } else {
              this.toastService.info('Already optimal (no better version)');
            }
          
            this.decisionMade.set(false);
            this.viewingVersionId.set(null);
          
            this.loadJob(newJobId);
          
            setTimeout(() => {
              const newState = this.state();
              const storyId = newState?.user_story_id;
          
              if (storyId) {
                this.loadVersions(storyId);
              }
            }, 600);
          
            break;

          case 'failed':
            this.cleanupSSE();
            this.relaunching.set(false);
            this.toastService.error('Pipeline failed');
            this.navigateToStories();
            break;
        }
      },
      error: (err) => {
        console.error('[RELAUNCH SSE ERROR]', err);
        this.cleanupSSE();
        this.toastService.error('Connection lost');

        this.router.navigate(['/review', newJobId], {
          queryParams: {
            projectId: this.navProjectId,
            projectName: this.navProjectName,
            issueKey: this.issueKey,
          }
        });
      }
    });
  }

  // ─────────────────────────────────────────────
  // NAVIGATION
  // ─────────────────────────────────────────────

  private navigateToStories(): void {
    setTimeout(() => {
      this.router.navigate(['/user-stories'], {
        queryParams: {
          projectId: this.navProjectId,
          projectName: this.navProjectName,
          highlight: this.issueKey
        }
      });
    }, 1000);
  }

  goBack(): void {
    this.cleanupSSE();
    this.router.navigate(['/user-stories'], {
      queryParams: {
        projectId: this.navProjectId,
        projectName: this.navProjectName
      }
    });
  }

  // ─────────────────────────────────────────────
  // HELPERS
  // ─────────────────────────────────────────────

  formatScore(score: number | undefined | null): string {
    if (score === undefined || score === null || isNaN(score)) return '—';
    const displayScore = score <= 1 ? score * 10 : score;
    return displayScore.toFixed(1);
  }

  isJobCompleted(): boolean {
    return this.state()?.status === 'completed';
  }

  isJobFailed(): boolean {
    return this.state()?.status === 'failed';
  }

  isJobProcessing(): boolean {
    return this.state()?.status === 'processing';
  }

  formatDate(date: string | undefined): string {
    if (!date) return '';
    return new Date(date).toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  }
}