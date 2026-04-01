import { Component, OnInit, OnDestroy, signal, computed, inject, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { UserStory, SSEEvent, PipelineResponse } from '../../models';
import { StoriesService, PipelineService, SseService, ToastService, JobsService } from '../../services';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { EmptyStateComponent } from '../../shared/empty-state/empty-state.component';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { StoryDetailModalComponent } from '../../components/story-detail-modal/story-detail-modal.component';
import { ImportModalComponent } from '../../components/import-modal/import-modal.component';
import { environment } from '../../../environments/environment';

interface StoryJob {
  job_id: string;
  issue_key: string;
}

interface StoryWithJob extends UserStory {
  job?: StoryJob;
  jobPhase?: 'analyzing' | 'refining' | 'reanalyzing' | 'completed' | 'failed';
  jobScore?: number;
  jobIteration?: number;
}

@Component({
  selector: 'app-user-stories',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    SpinnerComponent,
    EmptyStateComponent,
    ScoreBadgeComponent,
    SearchBarComponent,
    FilterBarComponent,
    PaginationComponent,
    StoryDetailModalComponent,
    ImportModalComponent,
  ],
  templateUrl: './user-stories.component.html',
  styleUrl: './user-stories.component.scss',
})
export class UserStoriesComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private storiesService = inject(StoriesService);
  private pipelineService = inject(PipelineService);
  private sseService = inject(SseService);
  private jobsService = inject(JobsService);
  private toastService = inject(ToastService);

  @ViewChild('importModal') importModal!: ImportModalComponent;

  // ─── State ──────────────────────────────────────────────────────
  stories = signal<StoryWithJob[]>([]);
  loading = signal(true);
  pipelineLoading = signal(false);
  selectedStory = signal<StoryWithJob | null>(null);

  // Pagination
  page = signal(1);
  pageSize = signal(10);

  // Search
  private searchQuery = signal('');

  // Filters
  activeFilters = signal<ActiveFilters>({});

  // Route params
  projectId = signal<string | null>(null);
  projectName = signal<string | null>(null);

  // Selection
  private selectedKeys = signal<Set<string>>(new Set());

  // SSE subscriptions
  private sseSubscriptions = new Map<string, Subscription>();

  // Phase queue system
  private readonly MIN_PHASE_DURATION = 800;
  private phaseTimers = new Map<string, { phase: string; startTime: number }>();
  private phaseQueues = new Map<string, Array<{
    job: StoryJob;
    phase: StoryWithJob['jobPhase'];
    score?: number;
    iteration?: number;
  }>>();
  private phaseProcessing = new Map<string, boolean>();

  // ─── Filter config ──────────────────────────────────────────────

  filterGroups: FilterGroup[] = [
    {
      key: 'priority',
      label: 'Priority',
      multiple: true,
      options: [
        { value: 'highest', label: 'Highest' },
        { value: 'high',    label: 'High' },
        { value: 'medium',  label: 'Medium' },
        { value: 'low',     label: 'Low' },
        { value: 'lowest',  label: 'Lowest' },
      ],
    },
    {
      key: 'pipeline',
      label: 'Pipeline Status',
      multiple: true,
      options: [
        { value: 'idle',       label: 'Not processed' },
        { value: 'processing', label: 'In progress' },
        { value: 'completed',  label: 'Completed' },
        { value: 'failed',     label: 'Failed' },
      ],
    },
    {
      key: 'ac',
      label: 'Acceptance Criteria',
      multiple: false,
      options: [
        { value: 'has_ac', label: 'Has AC' },
        { value: 'no_ac',  label: 'No AC' },
      ],
    },
  ];

  // ─── Computed ───────────────────────────────────────────────────

  filteredStories = computed(() => {
    let result = this.stories();
    const query = this.searchQuery().toLowerCase().trim();
    const filters = this.activeFilters();

    // Text search
    if (query) {
      result = result.filter(story =>
        story.issue_key.toLowerCase().includes(query) ||
        (story.title?.toLowerCase().includes(query)) ||
        (story.description?.toLowerCase().includes(query))
      );
    }

    // Priority filter
    if (filters['priority']?.length) {
      result = result.filter(s =>
        filters['priority'].includes(s.priority?.toLowerCase() ?? '')
      );
    }

    // Pipeline status filter
    if (filters['pipeline']?.length) {
      result = result.filter(s => {
        const status = this.getPipelineStatus(s);
        return filters['pipeline'].includes(status);
      });
    }

    // AC filter
    if (filters['ac']?.length) {
      const wantAc = filters['ac'].includes('has_ac');
      const wantNoAc = filters['ac'].includes('no_ac');
      if (wantAc && !wantNoAc) {
        result = result.filter(s => this.getAcCount(s) > 0);
      } else if (wantNoAc && !wantAc) {
        result = result.filter(s => this.getAcCount(s) === 0);
      }
    }

    return result;
  });

  paginatedStories = computed(() => {
    const all = this.filteredStories();
    const start = (this.page() - 1) * this.pageSize();
    return all.slice(start, start + this.pageSize());
  });

  selectedCount = computed(() => this.selectedKeys().size);

  allSelected = computed(() => {
    const stories = this.filteredStories();
    return stories.length > 0 && stories.every(s => this.selectedKeys().has(s.issue_key));
  });

  someSelected = computed(() => {
    const stories = this.filteredStories();
    const selected = stories.filter(s => this.selectedKeys().has(s.issue_key));
    return selected.length > 0 && selected.length < stories.length;
  });

  // ─── Lifecycle ──────────────────────────────────────────────────

  ngOnInit(): void {
    this.route.queryParams.subscribe(params => {
      this.projectId.set(params['projectId'] || null);
      this.projectName.set(params['projectName'] || null);
      this.loadStories();
    });
  }

  ngOnDestroy(): void {
    this.sseService.disconnectAll();
    this.sseSubscriptions.forEach(sub => sub.unsubscribe());
  }

  // ─── Load stories ───────────────────────────────────────────────

  private loadStories(): void {
    this.loading.set(true);
    const projectId = this.projectId();

    const request$ = projectId
      ? this.storiesService.getStoriesByProject(projectId)
      : this.storiesService.getAllStories();

    request$.subscribe({
      next: (stories) => {
        this.stories.set(stories.map(s => ({ ...s })));
        this.loading.set(false);
        this.restorePendingJobs();
      },
      error: (err) => {
        console.error('Failed to load stories:', err);
        this.toastService.error('Failed to load stories');
        this.loading.set(false);
      },
    });
  }

  private restorePendingJobs(): void {
    this.jobsService.getPendingJobs().subscribe({
      next: (pendingJobs) => {
        if (!pendingJobs || Object.keys(pendingJobs).length === 0) return;

        this.stories.update(stories =>
          stories.map(s => {
            const pending = pendingJobs[s.issue_key];
            if (pending && !s.final) {
              return {
                ...s,
                job: {
                  job_id: pending.job_id,
                  issue_key: pending.issue_key,
                },
                jobPhase: 'completed' as const,
                jobScore: pending.score_after,
                jobIteration: pending.iteration,
              };
            }
            return s;
          })
        );
      },
      error: (err) => {
        console.error('Failed to load pending jobs:', err);
      },
    });
  }

  // ─── Search handler ─────────────────────────────────────────────

  onSearchChange(query: string): void {
    this.searchQuery.set(query);
    this.page.set(1);
  }

  // ─── Filter handlers ───────────────────────────────────────────

  onFiltersChange(filters: ActiveFilters): void {
    this.activeFilters.set(filters);
    this.page.set(1);
  }

  clearAllFilters(): void {
    this.searchQuery.set('');
    this.activeFilters.set({});
    this.page.set(1);
  }

  // ─── Pagination handlers ────────────────────────────────────────

  onPageChange(p: number): void {
    this.page.set(p);
  }

  onPageSizeChange(size: number): void {
    this.pageSize.set(size);
    this.page.set(1);
  }

  // ─── Navigation ─────────────────────────────────────────────────

  goBack(): void {
    this.router.navigate(['/dashboard']);
  }

  // ─── Import ─────────────────────────────────────────────────────

  openImportModal(): void {
    this.importModal.open();
  }

  onImported(): void {
    this.loadStories();
  }

  // ─── Modal ──────────────────────────────────────────────────────

  openStoryDetail(story: StoryWithJob): void {
    this.selectedStory.set(story);
  }

  closeModal(): void {
    this.selectedStory.set(null);
  }

  // ─── Selection ──────────────────────────────────────────────────

  isSelected(story: StoryWithJob): boolean {
    return this.selectedKeys().has(story.issue_key);
  }

  toggleSelect(story: StoryWithJob): void {
    const keys = new Set(this.selectedKeys());
    if (keys.has(story.issue_key)) {
      keys.delete(story.issue_key);
    } else {
      keys.add(story.issue_key);
    }
    this.selectedKeys.set(keys);
  }

  toggleSelectAll(): void {
    const stories = this.filteredStories();
    if (this.allSelected()) {
      this.selectedKeys.set(new Set());
    } else {
      this.selectedKeys.set(new Set(stories.map(s => s.issue_key)));
    }
  }

  // ─── Utils ──────────────────────────────────────────────────────

  getAcList(story: UserStory): string[] {
    const ac = story.acceptance_criteria;
    if (!ac) return [];
    if (Array.isArray(ac)) {
      return ac.filter(item => item && String(item).trim());
    }
    if (typeof ac === 'string') {
      return ac.split('\n').filter(line => line.trim());
    }
    return [];
  }

  getAcCount(story: UserStory): number {
    return this.getAcList(story).length;
  }

  private getPipelineStatus(story: StoryWithJob): string {
    if (story.final) return 'completed';
    if (story.jobPhase === 'failed') return 'failed';
    if (story.job) return 'processing';
    return 'idle';
  }

  // ─── Pipeline ───────────────────────────────────────────────────

  rerunPipeline(story: StoryWithJob): void {
    this.runPipeline([story.issue_key]);
  }

  viewResults(story: StoryWithJob): void {
    if (story.job && !story.final) {
      this.router.navigate(['/review', story.job.job_id]);
    } else if (story.final) {
      this.openStoryDetail(story);
    }
  }

  runSinglePipeline(story: StoryWithJob): void {
    this.runPipeline([story.issue_key]);
  }

  runSelectedPipeline(): void {
    const keys = Array.from(this.selectedKeys());
    if (keys.length > 0) {
      this.runPipeline(keys);
      this.selectedKeys.set(new Set());
    }
  }

  runAllPipeline(): void {
    const keys = this.stories().map(s => s.issue_key);
    this.runPipeline(keys);
  }

  private runPipeline(issueKeys: string[]): void {
    this.pipelineLoading.set(true);

    this.pipelineService.runPipelineByKeys(issueKeys).subscribe({
      next: (response: PipelineResponse) => {
        this.pipelineLoading.set(false);

        if (response.jobs && response.jobs.length > 0) {
          response.jobs.forEach(job => {
            this.disconnectJob(job.job_id);
            this.phaseQueues.delete(job.issue_key);
            this.phaseProcessing.delete(job.issue_key);
            this.phaseTimers.delete(job.issue_key);

            this.stories.update(stories =>
              stories.map(s =>
                s.issue_key === job.issue_key
                  ? {
                      ...s,
                      final: null,
                      job: {
                        job_id: job.job_id,
                        issue_key: job.issue_key,
                      },
                      jobPhase: 'analyzing' as const,
                      jobScore: undefined,
                      jobIteration: 0,
                    }
                  : s
              )
            );

            this.phaseTimers.set(job.issue_key, { phase: 'analyzing', startTime: Date.now() });
            this.connectSSE(job.job_id, job.issue_key);
          });

          this.toastService.success(
            `Pipeline started for ${response.jobs.length} stories`
          );
        } else {
          this.toastService.warning('No stories to process');
        }
      },
      error: (err) => {
        console.error('Pipeline error:', err);
        this.toastService.error('Failed to start pipeline');
        this.pipelineLoading.set(false);
      },
    });
  }

  // ─── Phase queue system ─────────────────────────────────────────

  private updateStoryJob(
    issueKey: string,
    job: StoryJob,
    phase: StoryWithJob['jobPhase'],
    score?: number,
    iteration?: number
  ): void {
    if (!this.phaseQueues.has(issueKey)) {
      this.phaseQueues.set(issueKey, []);
    }

    const queue = this.phaseQueues.get(issueKey)!;

    if (phase === 'completed' || phase === 'failed') {
      queue.push({ job, phase, score, iteration });
      if (!this.phaseProcessing.get(issueKey)) {
        this.phaseProcessing.set(issueKey, true);
        this.drainNext(issueKey);
      }
      return;
    }

    if (!this.phaseProcessing.get(issueKey)) {
      this.phaseProcessing.set(issueKey, true);
      this.applyPhaseUpdate(issueKey, job, phase, score, iteration);
      this.scheduleNextPhase(issueKey);
    } else {
      const existingIdx = queue.findIndex(q => q.phase === phase);
      if (existingIdx !== -1) {
        queue[existingIdx] = { job, phase, score, iteration };
      } else {
        queue.push({ job, phase, score, iteration });
      }
    }
  }

  private applyPhaseUpdate(
    issueKey: string,
    job: StoryJob,
    phase: StoryWithJob['jobPhase'],
    score?: number,
    iteration?: number
  ): void {
    const now = Date.now();
    this.phaseTimers.set(issueKey, { phase: phase!, startTime: now });

    this.stories.update(stories =>
      stories.map(s =>
        s.issue_key === issueKey
          ? {
              ...s,
              job,
              jobPhase: phase,
              jobScore: score !== undefined ? score : s.jobScore,
              jobIteration: iteration !== undefined ? iteration : s.jobIteration,
            }
          : s
      )
    );
  }

  private drainNext(issueKey: string): void {
    const queue = this.phaseQueues.get(issueKey);
    if (!queue || queue.length === 0) {
      this.phaseProcessing.set(issueKey, false);
      return;
    }

    const next = queue.shift()!;
    this.applyPhaseUpdate(issueKey, next.job, next.phase, next.score, next.iteration);

    if (next.phase === 'completed' || next.phase === 'failed') {
      setTimeout(() => {
        this.phaseProcessing.set(issueKey, false);
        this.phaseTimers.delete(issueKey);
        this.phaseQueues.delete(issueKey);
        this.phaseProcessing.delete(issueKey);
      }, this.MIN_PHASE_DURATION);
      return;
    }

    this.scheduleNextPhase(issueKey);
  }

  private scheduleNextPhase(issueKey: string): void {
    setTimeout(() => {
      this.drainNext(issueKey);
    }, this.MIN_PHASE_DURATION);
  }

  // ─── SSE ────────────────────────────────────────────────────────

  private connectSSE(jobId: string, issueKey: string): void {
    const url = `${environment.apiUrl}/jobs/${jobId}/stream`;

    const subscription = this.sseService.connect(url, jobId).subscribe({
      next: (event) => this.handleSSEEvent(issueKey, event),
      error: (err) => {
        console.error(`[SSE] Error for ${issueKey}:`, err);
        this.disconnectJob(jobId);
      },
    });

    this.sseSubscriptions.set(jobId, subscription);
  }

  private normalizeScore(score: number): number {
    return score <= 1 ? score * 10 : score;
  }

  private handleSSEEvent(issueKey: string, event: SSEEvent): void {
    const story = this.stories().find(s => s.issue_key === issueKey);
    if (!story || !story.job) return;

    const job = story.job;
    const data = event.data || {};

    switch (event.type) {
      case 'job_started':
      case 'analysis_started':
        if (!data.reanalysis) {
          this.updateStoryJob(issueKey, job, 'analyzing', undefined, data.iteration ?? 0);
        } else {
          this.updateStoryJob(issueKey, job, 'reanalyzing', undefined, data.iteration);
        }
        break;

      case 'analysis_completed':
        break;

      case 'refinement_started':
        this.updateStoryJob(issueKey, job, 'refining', undefined, data.iteration + 1);
        break;

      case 'refinement_completed':
        break;

      case 'rescoring':
        this.updateStoryJob(issueKey, job, 'reanalyzing', this.normalizeScore(data.score_after), data.iteration);
        break;

      case 'job_completed':
        this.updateStoryJob(issueKey, job, 'completed', this.normalizeScore(data.score_after ?? data.score), data.iteration);
        break;

      case 'job_failed':
        this.updateStoryJob(issueKey, job, 'failed');
        break;

      case 'ping':
        break;
    }
  }

  private disconnectJob(jobId: string): void {
    this.sseService.disconnect(jobId);
    const sub = this.sseSubscriptions.get(jobId);
    if (sub) {
      sub.unsubscribe();
      this.sseSubscriptions.delete(jobId);
    }
  }
}