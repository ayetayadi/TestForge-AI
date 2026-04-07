import { Component, OnInit, OnDestroy, signal, computed, inject, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { UserStory, UserStoryVersion, SSEEvent, PipelineResponse, StoryWithJob, StoryJob } from '../../models';
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
      const highlightKey = params['highlight'];
      this.loadStories();
      if (highlightKey) {
    setTimeout(() => {
      this.scrollToStory(highlightKey);
    }, 500); // petit délai pour attendre le render
  }
    });
    
  }

  private scrollToStory(issueKey: string): void {
  const element = document.getElementById(`story-${issueKey}`);
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

  ngOnDestroy(): void {
    console.log("[COMPONENT DESTROYED] cleaning up subscriptions");
    this.sseSubscriptions.forEach((sub) => {
      sub.unsubscribe();
    });
    this.sseSubscriptions.clear();
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
        const storiesWithJob: StoryWithJob[] = stories.map(s => ({
          ...s,
          job: undefined,
          jobPhase: undefined,
          jobScore: undefined,
          jobIteration: undefined,
          selected_version: undefined,
          latest_version: undefined,
        }));
        
        this.stories.set(storiesWithJob);
        this.loading.set(false);

        this.recoverJobStates();
      },
      error: (err) => {
        console.error('Failed to load stories:', err);
        this.toastService.error('Failed to load stories');
        this.loading.set(false);
      },
    });
  }

  // ─── Recover job states after page load/navigation ──────────────
private recoverJobStates(): void {
  const stories = this.stories();
  if (stories.length === 0) return;

  const issueKeys = stories.map(s => s.issue_key);

  this.jobsService.getJobsByIssues(issueKeys).subscribe({
    next: (jobsMap) => {

      this.stories.update(currentStories => {
        const updatedStories = currentStories.map((s: StoryWithJob) => {
          const jobData = jobsMap[s.issue_key];

          if (!jobData) return s;

          const updated: StoryWithJob = {
            ...s,
            job: {
              job_id: jobData.job_id,
              issue_key: s.issue_key,
            },
            jobPhase: jobData.phase,
            jobScore: jobData.final_score,
            jobIteration: jobData.iteration,
            decision_status: jobData.decision_status,
          };

          if (jobData.status === 'completed') {
            updated.latest_version = jobData.improved_story
              ? {
                  id: jobData.version_id,
                  story_id: s.id,
                  job_id: jobData.job_id,
                  improved_story: jobData.improved_story,
                  acceptance_criteria: jobData.acceptance_criteria || [],
                  initial_score: jobData.initial_score || 0,
                  final_score: jobData.final_score || 0,
                  score_delta: jobData.score_delta || 0,
                  iteration: jobData.iteration || 1,
                  is_selected: false,
                }
              : undefined;
          }

          if (jobData.status === 'processing') {
            this.reconnectSSE(s.issue_key, jobData.job_id);
          }

          return updated;
        });

        setTimeout(() => {
          updatedStories.forEach((story: StoryWithJob) => {
            this.loadVersionsForStory(story.issue_key);
          });
        });

        return updatedStories;
      });

    },
    error: (err) => console.error('[RECOVER] Error:', err),
  });
}

private loadVersionsForStory(issueKey: string): void {
  this.storiesService.getStoryByIssueKey(issueKey).subscribe({
    next: (updated: any) => {

      console.log('[VERSIONS]', updated);

      let selectedVersion = updated.selected_version ?? null;

      if (!selectedVersion && updated.selected_version_id && updated.latest_version) {
        if (updated.latest_version.id === updated.selected_version_id) {
          selectedVersion = updated.latest_version;
        }
      }

      this.stories.update(stories =>
        stories.map((s: StoryWithJob) =>
          s.issue_key === issueKey
            ? {
                ...s,
                selected_version: selectedVersion,
                latest_version: updated.latest_version ?? s.latest_version
              }
            : s
        )
      );
    },
    error: (err) => console.error('[VERSIONS LOAD ERROR]', err)
  });
}

private reconnectSSE(issueKey: string, jobId: string): void {
  if (!this.sseService.isConnected(jobId) && !this.sseSubscriptions.has(jobId)) {
    console.log("[SSE RECONNECT]", issueKey, jobId);
    this.connectSSE(jobId, issueKey);
  }
}


// Ajouter ces méthodes dans la section Utils

/**
 * Vérifie si une story est en cours de processing
 */
isProcessing(story: StoryWithJob): boolean {
  if (!story.job || !story.jobPhase) return false;
  return !['completed', 'failed'].includes(story.jobPhase);
}

/**
 * Retourne le label de la phase actuelle
 */
getPhaseLabel(story: StoryWithJob): string {
  const phase = story.jobPhase;
  const iteration = story.jobIteration;

  switch (phase) {
    case 'analyzing':
      return 'Analyzing...';
    case 'refining':
      return iteration && iteration > 0 
        ? `Refining #${iteration}` 
        : 'Refining...';
    case 'evaluating':
      return iteration && iteration > 0 
        ? `Evaluating #${iteration}` 
        : 'Evaluating...';
    default:
      return 'Processing...';
  }
}

/**
 * Retourne le statut de décision effectif
 * - rejected_relaunch → devient pending car nouvelle version créée
 */
getDecisionStatus(story: StoryWithJob): string {
  const status = story.decision_status;
  
  // rejected_relaunch n'est pas un état final
  // Après relaunch, une nouvelle version existe = pending
  if (status === 'rejected_relaunch') {
    return 'pending';
  }
  
  return status || 'pending';
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
    this.router.navigate(['/projects']);
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

  // ─── Version Helper ─────────────────────────────────────────────
  
  /**
   * Retourne la version à afficher:
   * - selected_version si l'utilisateur a fait un choix
   * - sinon latest_version (dernière du pipeline)
   */
  getDisplayVersion(story: StoryWithJob): UserStoryVersion | null {
    return story.selected_version ?? story.latest_version ?? null;
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

  /**
   * Détermine le statut pipeline pour les filtres
   */
  private getPipelineStatus(story: StoryWithJob): string {
    if (story.jobPhase === 'failed') return 'failed';
    if (story.jobPhase === 'completed') return 'completed';
    if (story.jobPhase && story.job) return 'processing';
    
    // Vérifie s'il y a une version (selected ou latest)
    if (story.job) return 'completed';
    
    return 'idle';
  }


isCompleted(story: StoryWithJob): boolean {
  // ✅ Si un pipeline est en cours, ce n'est PAS completed
  if (story.job && story.jobPhase && !['completed', 'failed'].includes(story.jobPhase)) {
    return false;
  }

  // Kept original = completed (seulement si pas de pipeline en cours)
  if (story.decision_status === 'rejected_keep') {
    return true;
  }

  const hasVersion = this.getDisplayVersion(story) !== null;
  if (!hasVersion) return false;

  return true;
}

  /**
   * Vérifie si on peut lancer un nouveau pipeline
   * - Pas de job en cours
   * - Ou job terminé (completed/failed)
   */
  canRunPipeline(story: StoryWithJob): boolean {
    if (!story.job) return true;
    if (!story.jobPhase) return true;
    return ['completed', 'failed'].includes(story.jobPhase);
  }

  /**
   * Vérifie si on peut re-lancer le pipeline (a déjà des résultats)
   */
  canRerunPipeline(story: StoryWithJob): boolean {
    return this.getDisplayVersion(story) !== null && this.canRunPipeline(story);
  }

  // ─── Pipeline ───────────────────────────────────────────────────

  rerunPipeline(story: StoryWithJob): void {
    this.runPipeline([story.issue_key]);
  }

  viewResults(story: StoryWithJob): void {
    const version = this.getDisplayVersion(story);
    const jobId = story.job?.job_id || version?.job_id;
    
    if (!jobId) {
      console.error("❌ No job_id for review");
      this.toastService.error("No results available");
      return;
    }

    this.router.navigate(['/review', jobId], {
      queryParams: { issueKey: story.issue_key }
    });
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

  const storiesBeingRelaunched = this.stories().filter(s => 
    issueKeys.includes(s.issue_key) && s.decision_status === 'rejected_keep'
  );

  this.pipelineService.runPipelineByKeys(issueKeys).subscribe({
    next: (response: PipelineResponse) => {
      this.pipelineLoading.set(false);

      if (response.jobs && response.jobs.length > 0) {
        response.jobs.forEach(job => {
          // Cleanup previous state
          this.disconnectJob(job.job_id);
          this.phaseQueues.delete(job.issue_key);
          this.phaseProcessing.delete(job.issue_key);
          this.phaseTimers.delete(job.issue_key);

          this.stories.update(stories =>
            stories.map(s =>
              s.issue_key === job.issue_key
                ? {
                    ...s,
                    latest_version: undefined,
                    job: {
                      job_id: job.job_id,
                      issue_key: job.issue_key,
                    },
                    jobPhase: 'analyzing',
                    jobIteration: 0,
                    jobScore: undefined,
                    decision_status: 'pending',
                  }
                : s
            )
          );

          this.phaseTimers.set(job.issue_key, { 
            phase: 'analyzing', 
            startTime: Date.now() 
          });
          
          this.connectSSE(job.job_id, job.issue_key);
        });

        // ✅ Message différent selon le contexte
        if (storiesBeingRelaunched.length > 0) {
          this.toastService.info(
            `${storiesBeingRelaunched.length} story(ies) previously rejected (kept original) — reusing cached results`
          );
        } else {
          const count = response.jobs.length;
          const label = count === 1 ? 'user story' : 'user stories';
          this.toastService.success(
            `Pipeline started for ${count} ${label}`
          );
        }

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
    if (this.sseSubscriptions.has(jobId)) {
      console.log("[SSE] Already subscribed to", jobId);
      return;
    }

    const url = `${environment.apiUrl}/jobs/${jobId}/stream`;
    console.log("[CONNECT SSE]", jobId);

    const subscription = this.sseService.connect(url, jobId).subscribe({
      next: (event) => this.handleSSEEvent(issueKey, event),
      error: (err) => {
        console.error(`[SSE] Error for ${issueKey}:`, err);
        this.sseSubscriptions.delete(jobId);
        
        setTimeout(() => {
          this.loadJobState(jobId, issueKey);
        }, 1000);
      },
      complete: () => {
        console.log(`[SSE] Stream completed for ${issueKey}`);
        this.sseSubscriptions.delete(jobId);
      }
    });

    this.sseSubscriptions.set(jobId, subscription);
  }

private handleSSEEvent(issueKey: string, event: SSEEvent): void {
  const story = this.stories().find(s => s.issue_key === issueKey);
  if (!story?.job) {
    console.warn("[SSE] No story/job found for", issueKey);
    return;
  }

  const job = story.job;
  const data = event.data || {};

  console.log("[EVENT]", issueKey, event.type, data);

  switch (event.type) {
    case 'analyzing':
    case 'refining':
    case 'evaluating':
      this.updateStoryJob(
        issueKey,
        job,
        event.type as StoryWithJob['jobPhase'],
        undefined,
        data.iteration
      );
      break;

case 'completed':
  this.updateStoryJob(issueKey, job, 'completed', data.final_score, data.iteration);

  this.stories.update(stories =>
    stories.map(s => {
      if (s.issue_key !== issueKey) return s;

      if (!data.version_id) {
        console.error("❌ Missing version_id", data);
        return s;
      }

      return {
        ...s,
        latest_version: {
          id: data.version_id,
          story_id: s.id,
          improved_story: data.improved_story ?? '',
          acceptance_criteria: data.acceptance_criteria ?? [],
          initial_score: data.initial_score ?? 0,
          final_score: data.final_score ?? 0,
          score_delta: (data.final_score ?? 0) - (data.initial_score ?? 0),
          iteration: data.iteration ?? 1,
          job_id: job.job_id,
          is_selected: false,
        },
      };
    })
  );
  break;
    case 'failed':
      this.updateStoryJob(issueKey, job, 'failed', undefined, data.iteration);
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

private loadJobState(jobId: string, issueKey: string): Promise<void> {
  return fetch(`${environment.apiUrl}/jobs/${jobId}`)
    .then(res => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then(state => {
      console.log("[JOB STATE]", issueKey, state);

      if (state.status === "completed" || state.status === "failed") {
        this.stories.update(stories =>
          stories.map(s => {
            if (s.issue_key !== issueKey) return s;

            // 🔴 GUARD CRITIQUE
            if (state.status === "completed" && !state.version_id) {
              console.error("❌ Missing version_id in job state", state);
              return s; // skip update
            }

            return {
              ...s,
              job: { job_id: jobId, issue_key: issueKey },
              jobPhase: state.status as 'completed' | 'failed',
              jobIteration: state.iteration ?? 0,
              latest_version: state.status === 'completed'
                ? {
                    id: state.version_id, // ✅ FIX
                    story_id: s.id,
                    improved_story: state.improved_story ?? '',
                    acceptance_criteria: state.acceptance_criteria ?? [],
                    initial_score: state.initial_score ?? 0,
                    final_score: state.final_score ?? 0,
                    score_delta: (state.final_score ?? 0) - (state.initial_score ?? 0),
                    iteration: state.iteration ?? 1,
                    job_id: jobId,
                    is_selected: false,
                  }
                : s.latest_version,
            };
          })
        );

        this.disconnectJob(jobId);
        return;
      }

      if (state.status === "processing") {
        this.stories.update(stories =>
          stories.map(s =>
            s.issue_key === issueKey
              ? {
                  ...s,
                  job: { job_id: jobId, issue_key: issueKey },
                  jobPhase: (state.phase as StoryWithJob['jobPhase']) ?? 'analyzing',
                  jobIteration: state.iteration ?? 0,
                  latest_version: undefined,
                }
              : s
          )
        );

        if (!this.sseService.isConnected(jobId) && !this.sseSubscriptions.has(jobId)) {
          console.log("[SSE RECONNECT]", jobId);
          this.connectSSE(jobId, issueKey);
        }
      }
    })
    .catch(err => {
      console.error("[JOB STATE ERROR]", err);
    });
}
}