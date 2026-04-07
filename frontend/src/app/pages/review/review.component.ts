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

  // Pipeline step indicator
  step = signal<'analysis' | 'refinement' | 'done' | 'idle'>('idle');

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
    
    // Si on a sélectionné une version spécifique
    if (viewingId) {
      const found = versions.find(v => v.id === viewingId);
      if (found) return found;
    }
    
    // Chercher la version du job actuel par version_id
    if (state?.version_id && versions.length > 0) {
      const found = versions.find(v => v.id === state.version_id);
      if (found) return found;
    }
    
    // Dernière version disponible
    if (versions.length > 0) {
      return versions[versions.length - 1];
    }
    
    // Fallback: créer une version virtuelle depuis le state
    if (state && state.improved_story) {
      return {
        id: state.version_id || 'virtual-' + state.job_id,
        story_id: state.story_id || '',
        job_id: state.job_id,
        improved_story: state.improved_story,
        acceptance_criteria: state.acceptance_criteria || [],
        initial_score: state.initial_score || 0,
        final_score: state.final_score || 0,
        score_delta: (state.final_score || 0) - (state.initial_score || 0),
        iteration: state.iteration || 0,
        is_selected: false,
      } as UserStoryVersion;
    }
    
    return null;
  });

  /**
   * Vérifie si on regarde la dernière version (la plus récente)
   */
  isViewingLatestVersion = computed(() => {
    const versions = this.allVersions();
    
    // Pas de versions chargées = on regarde le job directement = c'est la dernière
    if (versions.length === 0) return true;
    
    const current = this.currentVersion();
    if (!current) return true;
    
    // La dernière version est la dernière du tableau (trié par created_at)
    const latestVersion = versions[versions.length - 1];
    return current.id === latestVersion.id;
  });

  /**
   * Retourne le numéro de la version actuelle (1, 2, 3...)
   */
  getCurrentVersionNumber = computed(() => {
    const versions = this.allVersions();
    const current = this.currentVersion();
    
    if (!current || versions.length === 0) return 1;
    
    const index = versions.findIndex(v => v.id === current.id);
    return index >= 0 ? index + 1 : versions.length;
  });

  /**
   * Vérifie si la story a une décision FINALE (approved ou rejected_keep)
   * rejected_relaunch n'est PAS une décision finale car une nouvelle version est créée
   */
  hasFinalDecision = computed(() => {
    const s = this.state();
    const decision = s?.decision_status;
    return decision === 'approved' || decision === 'rejected_keep';
  });

  /**
   * Vérifie si on peut prendre une décision
   * - Job doit être completed
   * - Doit être sur la dernière version
   * - Pas de décision finale déjà prise
   * - Pas en train de relancer
   * - Pas déjà décidé dans cette session
   */
  canMakeDecision = computed(() => {
    const s = this.state();
    
    // Pas de state ou job pas terminé
    if (!s || s.status !== 'completed') return false;
    
    // En train de relancer
    if (this.relaunching()) return false;
    
    // Décision prise dans cette session
    if (this.decisionMade()) return false;
    
    // Doit être sur la dernière version
    // if (!this.isViewingLatestVersion()) return false;
    
    // Si décision finale déjà prise (approved ou rejected_keep)
    if (this.hasFinalDecision()) return false;
    
    return true;
  });

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
    return versions.find(v => v.is_selected) ?? null;
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
    this.step.set('idle');
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

        switch (event.type) {
          case 'analyzing':
            this.step.set('analysis');
            break;
          case 'refining':
          case 'evaluating':
            this.step.set('refinement');
            break;
          case 'completed':
            this.cleanupSSE();
            this.step.set('done');
            this.loadJob(jobId);
            break;
          case 'failed':
            this.cleanupSSE();
            this.step.set('done');
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

        // Update issue key if not set
        if (!this.issueKey && jobState.issue_key) {
          this.issueKey = jobState.issue_key;
        }

        // Load all versions for this story
        if (jobState.story_id) {
          this.loadVersions(jobState.story_id);
        } else {
          this.loading.set(false);
        }

        // Handle different statuses
        const status = jobState.status;
        const phase = jobState.phase;

        if (status === 'processing' && !this.relaunching()) {
          if (phase === 'analyzing') {
            this.step.set('analysis');
          } else {
            this.step.set('refinement');
          }
          this.listenToStream(jobId);
        } else if (status === 'completed' || status === 'failed') {
          this.step.set('done');
        }

        // Navigation context from job
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
      .then((versions: UserStoryVersion[]) => {
        console.log("[VERSIONS]", versions);
        this.allVersions.set(versions || []);
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

  /**
   * Sélectionne une version à afficher
   */
  viewVersion(version: UserStoryVersion): void {
    this.viewingVersionId.set(version.id);
  }

  /**
   * Retourne à la dernière version
   */
  viewLatestVersion(): void {
    const versions = this.allVersions();
    if (versions.length > 0) {
      const latest = versions[versions.length - 1];
      this.viewingVersionId.set(latest.id);
    } else {
      this.viewingVersionId.set(null);
    }
  }

  /**
   * Vérifie si une version est celle qu'on regarde
   */
  isViewing(version: UserStoryVersion): boolean {
    return this.currentVersion()?.id === version.id;
  }

  /**
   * Vérifie si c'est la dernière version
   */
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
    return this.currentVersion()?.score_delta ?? (this.getFinalScore() - this.getOriginalScore());
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
    if (version?.acceptance_criteria) {
      return version.acceptance_criteria;
    }
    return this.parseAc(this.state()?.acceptance_criteria);
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

      return ac.split('\n').map(x => x.trim()).filter(Boolean);
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

  // ─────────────────────────────────────────────
  // DECISION
  // ─────────────────────────────────────────────

  submitDecision(choice: DecisionChoice): void {
    if (!this.jobId || this.submitting() || !this.canMakeDecision()) return;

    // On approuve/rejette la version actuellement affichée (doit être la dernière)
    const versionId = this.currentVersion()?.id;

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
            this.toastService.info('Keeping original version');
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
  this.relaunchPhase.set('Starting...');

  this.jobId = newJobId;

  // ✅ connecter SSE AVANT tout
  this.connectRelaunchSSE(newJobId);

  // ❌ PAS de double load
  this.loadJob(newJobId);
}

  private connectRelaunchSSE(newJobId: string): void {
    this.cleanupSSE();

    const url = `${environment.apiUrl}/jobs/${newJobId}/stream`;

    this.sseSubscription = this.sseService.connect(url, newJobId).subscribe({
      next: (event: SSEEvent) => {
        console.log('[RELAUNCH SSE]', event.type, event.data);

        switch (event.type) {
          case 'analyzing':
            this.relaunchPhase.set('Analyzing...');
            break;

          case 'refining':
            this.relaunchPhase.set(`Refining... (iteration ${event.data?.iteration || 1})`);
            break;

          case 'evaluating':
            this.relaunchPhase.set(`Evaluating... (iteration ${event.data?.iteration || 1})`);
            break;

          case 'completed':
            this.cleanupSSE();
            this.relaunching.set(false);
            this.jobsService.getJob(newJobId).subscribe(job => {
          
              if (!job.has_new_version) {
                this.toastService.info('Already optimal — no new version created');
              } else {
                this.toastService.success('New version created');
              }

              this.viewingVersionId.set(null);
          
              this.router.navigate(['/review', newJobId], {
                queryParams: {
                  projectId: this.navProjectId,
                  projectName: this.navProjectName,
                  issueKey: this.issueKey,
                },
                replaceUrl: true
              });          
            });
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