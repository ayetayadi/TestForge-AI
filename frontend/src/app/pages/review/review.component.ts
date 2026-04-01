import { Component, OnInit, OnDestroy, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { JobsService, ToastService, PipelineService, SseService } from '../../services';
import { DecisionChoice, JobState, PipelineResponse, SSEEvent, UserStory } from '../../models';
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

  jobId = '';
  state = signal<JobState | null>(null);
  loading = signal(true);
  error = signal<string | null>(null);
  submitting = signal(false);

  // Relaunch waiting state
  relaunching = signal(false);
  relaunchPhase = signal<string>('');

  // Track if a decision has been made in this session
  decisionMade = signal(false);

  // Store navigation context from query params
  private navProjectId: string | null = null;
  private navProjectName: string | null = null;

  // SSE subscription for relaunch waiting
  private sseSubscription: Subscription | null = null;

  ngOnInit(): void {
    // Capture navigation context once from query params
    this.route.queryParams.subscribe(params => {
      if (params['projectId']) this.navProjectId = params['projectId'];
      if (params['projectName']) this.navProjectName = params['projectName'];
    });

    this.route.params.subscribe(params => {
      this.jobId = params['jobId'];
      if (this.jobId) {
        this.decisionMade.set(false);
        this.relaunching.set(false);
        this.relaunchPhase.set('');
        this.loadJob();
      }
    });
  }

  ngOnDestroy(): void {
    this.cleanupSSE();
  }

  private cleanupSSE(): void {
    if (this.sseSubscription) {
      this.sseSubscription.unsubscribe();
      this.sseSubscription = null;
    }
    if (this.jobId) {
      this.sseService.disconnect(this.jobId);
    }
  }

  loadJob(): void {
    this.loading.set(true);
    this.error.set(null);

    this.jobsService.getJob(this.jobId).subscribe({
      next: (jobState) => {
        if (jobState.status === 'not_found') {
          this.error.set('Job result no longer available.');
          this.loading.set(false);
          return;
        }
        this.state.set(jobState);
        this.loading.set(false);

        // Extract navigation context from job state if not already set
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

  isAlreadyDecided(): boolean {
    const s = this.state();
    if (!s || s.status === 'not_found') return true;
    if (this.relaunching()) return true;
    return this.decisionMade();
  }

  // ─── Getters ────────────────────────────────────────────────────

  getIssueKey(): string {
    return this.state()?.jira_id || 'Unknown';
  }

  getOriginalScore(): number {
    return this.state()?.initial_score ?? 0;
  }

  getFinalScore(): number {
    return this.state()?.final_score ?? 0;
  }

  getDelta(): number {
    return this.getFinalScore() - this.getOriginalScore();
  }

  getIteration(): number {
    return this.state()?.iteration ?? 0;
  }

  getOriginalStory(): string {
    const s = this.state();
    return s?.initial_story || s?.raw_story || 'No original story';
  }

  getImprovedStory(): string {
    return this.state()?.improved_story || 'No improved story';
  }

  getOriginalAC(): string[] {
    const ac: string[] | string | undefined = this.state()?.existing_ac;
    return this.parseAcField(ac);
  }

  getImprovedAC(): string[] {
    const ac: string[] | string | undefined = this.state()?.acceptance_criteria;
    return this.parseAcField(ac);
  }

  private parseAcField(ac: string[] | string | undefined | null): string[] {
    if (!ac) return [];

    if (Array.isArray(ac)) {
      if (ac.length === 1 && typeof ac[0] === 'string') {
        return ac[0]
          .split(/\n|(?<=\.)\s+/)
          .map((s: string) => s.trim())
          .filter((s: string) => s.length > 0);
      }
      return ac.filter((s) => s && String(s).trim().length > 0);
    }

    if (typeof ac === 'string') {
      try {
        const parsed = JSON.parse(ac);
        if (Array.isArray(parsed)) return parsed;
      } catch {}

      return ac
        .split(/\n|(?<=\.)\s+/)
        .map((s: string) => s.trim())
        .filter((s: string) => s.length > 0);
    }

    return [];
  }

  getScoreExplanation(): string | null {
    const trace = this.state()?.trace || [];
    for (let i = trace.length - 1; i >= 0; i--) {
      if (trace[i]?.data?.justification) {
        return trace[i].data.justification;
      }
    }
    return null;
  }

  getTrace(): any[] {
    return this.state()?.trace || [];
  }

  formatScore(score: number | undefined | null): string {
    if (score === undefined || score === null || isNaN(score)) {
      return '—';
    }
    const displayScore = score <= 1 ? score * 10 : score;
    return displayScore.toFixed(1);
  }

  getTraceScore(entry: any): number | null {
    if (entry?.data?.final !== undefined) {
      return entry.data.final;
    }
    if (entry?.data?.current_score !== undefined) {
      return entry.data.current_score;
    }
    return null;
  }

  // ─── Decision handling ──────────────────────────────────────────

  submitDecision(choice: DecisionChoice): void {
    if (!this.jobId || this.submitting()) return;

    this.submitting.set(true);

    this.jobsService.sendDecision(this.jobId, choice).subscribe({
      next: (response: any) => {
        this.submitting.set(false);

        if (response.status === 'error') {
          this.toastService.error(response.message || 'Failed to submit decision');
          return;
        }

        // Mark decision as made so buttons hide
        this.decisionMade.set(true);

        switch (choice) {
          case 'approve':
            this.toastService.success('Story approved and saved');
            this.navigateToStories();
            break;

          case 'reject_keep':
            this.toastService.info('Original story kept');
            this.navigateToStories();
            break;

          case 'reject_relaunch':
            this.handleRelaunch(response);
            break;
        }
      },
      error: (err) => {
        this.submitting.set(false);
        console.error('Decision error:', err);
        this.toastService.error('Failed to submit decision');
      },
    });
  }

  // ─── Relaunch flow ──────────────────────────────────────────────

  private handleRelaunch(decisionResponse: any): void {
    const issueKey = decisionResponse.issue_key || this.state()?.jira_id;

    if (!issueKey) {
      this.toastService.error('Missing issue key for relaunch');
      this.navigateToStories();
      return;
    }

    // Show relaunch waiting UI
    this.relaunching.set(true);
    this.relaunchPhase.set('Starting pipeline...');

    this.pipelineService.runPipelineByKeys([issueKey]).subscribe({
      next: (pipelineRes: PipelineResponse) => {
        if (!pipelineRes.jobs?.length) {
          this.toastService.error('Pipeline returned no jobs');
          this.relaunching.set(false);
          this.navigateToStories();
          return;
        }

        const newJobId = pipelineRes.jobs[0].job_id;
        this.relaunchPhase.set('Analyzing story...');
        this.connectRelaunchSSE(newJobId, issueKey);
      },
      error: (err) => {
        console.error('Relaunch pipeline error:', err);
        this.toastService.error('Failed to relaunch pipeline');
        this.relaunching.set(false);
        this.navigateToStories();
      },
    });
  }

  private connectRelaunchSSE(newJobId: string, issueKey: string): void {
    // Clean up any previous SSE
    this.cleanupSSE();

    const url = `${environment.apiUrl}/jobs/${newJobId}/stream`;

    this.sseSubscription = this.sseService.connect(url, newJobId).subscribe({
      next: (event: SSEEvent) => {
        const data = event.data || {};

        switch (event.type) {
          case 'job_started':
          case 'analysis_started':
            if (data.reanalysis) {
              const iter = data.iteration ?? '';
              this.relaunchPhase.set(`Re-analyzing${iter ? ' (iteration ' + iter + ')' : ''}...`);
            } else {
              this.relaunchPhase.set('Analyzing story...');
            }
            break;

          case 'refinement_started':
            const refIter = (data.iteration ?? 0) + 1;
            this.relaunchPhase.set(`Refining story (iteration ${refIter})...`);
            break;

          case 'rescoring':
            this.relaunchPhase.set('Scoring improvements...');
            break;

          case 'job_completed':
            // Pipeline done — clean up and navigate to the new review
            this.cleanupSSE();
            this.sseService.disconnect(newJobId);
            this.relaunching.set(false);
            this.relaunchPhase.set('');
            this.toastService.success('Pipeline completed, loading results...');

            // Navigate to the new review page
            this.jobId = newJobId;
            this.decisionMade.set(false);
            this.router.navigate(['/review', newJobId], {
              queryParams: {
                projectId: this.navProjectId,
                projectName: this.navProjectName,
              },
              replaceUrl: true,
            });
            // Load the new job data
            this.loadJob();
            break;

          case 'job_failed':
            this.cleanupSSE();
            this.sseService.disconnect(newJobId);
            this.relaunching.set(false);
            this.relaunchPhase.set('');
            this.toastService.error('Pipeline failed during relaunch');
            this.navigateToStories();
            break;

          case 'ping':
            break;
        }
      },
      error: (err) => {
        console.error('SSE error during relaunch:', err);
        this.cleanupSSE();
        this.relaunching.set(false);
        this.relaunchPhase.set('');
        this.toastService.error('Lost connection during relaunch');

        // Fallback: try to navigate to the new review anyway
        this.router.navigate(['/review', newJobId], {
          queryParams: {
            projectId: this.navProjectId,
            projectName: this.navProjectName,
          },
        });
      },
    });
  }

  // ─── Navigation ─────────────────────────────────────────────────

  private navigateToStories(): void {
    const queryParams: any = {};
    if (this.navProjectId) queryParams['projectId'] = this.navProjectId;
    if (this.navProjectName) queryParams['projectName'] = this.navProjectName;

    this.router.navigate(['/user-stories'], { queryParams });
  }

  goBack(): void {
    this.cleanupSSE();
    this.navigateToStories();
  }
}