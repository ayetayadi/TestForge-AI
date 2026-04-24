import { Component, OnInit, OnDestroy, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';

import {
  UserStory, UserStoryVersion, SSEEvent, PipelineResponse, StoryWithVersion
} from '../../models/user_story.model';
import { StoriesService, PipelineService, VersionsService, ToastService } from '../../services';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';

@Component({
  selector: 'app-user-story-detail',
  standalone: true,
  imports: [CommonModule, SpinnerComponent, ScoreBadgeComponent],
  templateUrl: './user-story-detail.component.html',
  styleUrl: './user-story-detail.component.scss',
})
export class UserStoryDetailComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private storiesService = inject(StoriesService);
  private versionsService = inject(VersionsService);
  private pipelineService = inject(PipelineService);
  private toastService = inject(ToastService);

  story = signal<StoryWithVersion | null>(null);
  versions = signal<UserStoryVersion[]>([]);
  loading = signal(true);
  pipelineLoading = signal(false);

  private sseSubscription?: Subscription;
  private currentVersionId?: string;

  // ─── Computed ───────────────────────────────────────────────────

  displayVersion = computed(() => {
    const s = this.story();
    if (!s) return null;
    if (s.selected_version) return s.selected_version;
    return s.latest_version ?? null;
  });

  hasVersion = computed(() => this.displayVersion() !== null);

  isApproved = computed(() => this.displayVersion()?.decision_status === 'approved');
  isRejected = computed(() => this.displayVersion()?.decision_status === 'rejected');
  isPending = computed(() => this.displayVersion()?.decision_status === 'pending');
  isProcessing = computed(() => this.story()?.WorkflowStatus === 'processing');


    generateTestCase(): void {
    const s = this.story();
    if (!s) {
      this.toastService.warning('No story loaded');
      return;
    }

    // TODO: Implement test case generation logic
    console.log('Generate test case for story:', s.issue_key);
    this.toastService.info('Test case generation will be implemented soon');
  }
  canRunPipeline = computed(() => {
    const s = this.story();
    if (!s || this.isProcessing()) return false;
    return !s.version || ['completed', 'failed'].includes(s.WorkflowStatus ?? '');
  });

  canRerunPipeline = computed(() => {
    if (this.isProcessing()) return false;
    return this.hasVersion() && this.canRunPipeline();
  });

  metadata = computed(() => {
    const s = this.story();
    if (!s) return [];
    const meta: { label: string; value: string }[] = [];
    if (s.jira_status) meta.push({ label: 'Status', value: s.jira_status });
    if (s.priority) meta.push({ label: 'Priority', value: s.priority });
    if (s.issue_type) meta.push({ label: 'Type', value: s.issue_type });
    if (s.story_points) meta.push({ label: 'Points', value: String(s.story_points) });
    if (s.sprint) meta.push({ label: 'Sprint', value: s.sprint });
    if (s.assignee) meta.push({ label: 'Assignee', value: s.assignee });
    if (s.reporter) meta.push({ label: 'Reporter', value: s.reporter });
    if (s.epic_key) meta.push({ label: 'Epic', value: s.epic_key });
    if (s.fix_version) meta.push({ label: 'Fix Version', value: s.fix_version });
    return meta;
  });

  // ─── Lifecycle ──────────────────────────────────────────────────

  ngOnInit(): void {
    const storyId = this.route.snapshot.paramMap.get('storyId');
    if (storyId) {
      this.loadStory(storyId);
    }
  }

  ngOnDestroy(): void {
    this.disconnectSSE();
  }

  // ─── Data loading ────────────────────────────────────────────────

  private loadStory(storyId: string): void {
    this.loading.set(true);
    this.storiesService.getStoryById(storyId).subscribe({
      next: (raw: any) => {
        const story: StoryWithVersion = {
          ...raw,
          selected_version: raw.selected_version ?? null,
          latest_version: raw.latest_version ?? null,
          display_version: raw.display_version ?? raw.selected_version ?? raw.latest_version ?? null,
          versions: raw.versions ?? [],
          WorkflowStatus: raw.processing_version ? 'processing' :
                       (raw.selected_version || raw.latest_version) ? 'completed' : 'idle',
          version: raw.latest_version ? {
            version_id: raw.latest_version.id,
            issue_key: raw.issue_key,
          } : undefined,
          has_processing: !!raw.processing_version,
          versions_count: raw.versions_count ?? 0,
        };
        this.story.set(story);
        this.versions.set(raw.versions ?? []);
        this.loading.set(false);

        if (story.has_processing && raw.processing_version?.id) {
          this.connectSSE(raw.processing_version.id);
        }
      },
      error: (err) => {
        console.error('Failed to load story:', err);
        this.toastService.error('Failed to load user story');
        this.loading.set(false);
      },
    });
  }

  private reloadVersions(): void {
    const s = this.story();
    if (!s) return;
    this.versionsService.getStoryVersions(s.id).subscribe({
      next: (versions) => {
        this.versions.set(versions);
        const latest = versions[0] ?? null;
        const selected = versions.find(v => v.decision_status === 'approved') ?? null;
        this.story.update(current => current ? {
          ...current,
          versions,
          latest_version: latest,
          selected_version: selected ?? current.selected_version,
          display_version: selected ?? latest,
        } : current);
      },
      error: (err) => console.error('Failed to reload versions:', err),
    });
  }

  // ─── SSE ─────────────────────────────────────────────────────────

  private connectSSE(versionId: string): void {
    this.disconnectSSE();
    this.currentVersionId = versionId;
    this.sseSubscription = this.versionsService.connectToVersionStream(versionId).subscribe({
      next: (event) => this.handleSSEEvent(event, versionId),
      error: (err) => console.error('[SSE error]', err),
    });
  }

  private disconnectSSE(): void {
    if (this.sseSubscription) {
      this.sseSubscription.unsubscribe();
      this.sseSubscription = undefined;
    }
    if (this.currentVersionId) {
      this.versionsService.disconnectFromVersionStream(this.currentVersionId);
      this.currentVersionId = undefined;
    }
  }

  private handleSSEEvent(event: SSEEvent, versionId: string): void {
    const data = event.data || {};
    switch (event.type) {
      case 'processing':
        this.story.update(s => s ? { ...s, WorkflowStatus: 'processing', has_processing: true } : s);
        break;

      case 'completed':
        this.story.update(s => {
          if (!s) return s;
          const newVersion: UserStoryVersion = {
            id: data.version_id ?? versionId,
            user_story_id: s.id,
            improved_story: data.improved_story ?? '',
            generated_acceptance_criteria: data.generated_acceptance_criteria ?? [],
            initial_score: data.initial_score ?? 0,
            final_score: data.final_score ?? 0,
            workflow_status: 'completed',
            decision_status: 'pending',
            testability_score: data.testability_score,
            is_testable: data.is_testable,
            testability_issues: [],
          };
          return {
            ...s,
            WorkflowStatus: 'completed',
            has_processing: false,
            latest_version: newVersion,
            display_version: newVersion,
            version: { version_id: newVersion.id, issue_key: s.issue_key },
          };
        });
        setTimeout(() => this.reloadVersions(), 500);
        break;

      case 'failed':
        this.story.update(s => s ? { ...s, WorkflowStatus: 'failed', has_processing: false } : s);
        break;
    }
  }

  // ─── Actions ─────────────────────────────────────────────────────

  goBack(): void {
    const returnPage = this.route.snapshot.queryParamMap.get('page');
    const projectId = this.route.snapshot.queryParamMap.get('projectId');
    const projectName = this.route.snapshot.queryParamMap.get('projectName');

    const qp: Record<string, string> = {};
    if (returnPage) qp['page'] = returnPage;
    if (projectId) qp['projectId'] = projectId;
    if (projectName) qp['projectName'] = projectName;

    this.router.navigate(['/user-stories'], { queryParams: qp });
  }

  runPipeline(): void {
    const s = this.story();
    if (!s) return;
    this.pipelineLoading.set(true);
    this.pipelineService.runPipelineByKeys([s.issue_key]).subscribe({
      next: (response: PipelineResponse) => {
        this.pipelineLoading.set(false);
        if (response.versions?.length) {
          const v = response.versions[0];
          this.story.update(current => current ? {
            ...current,
            WorkflowStatus: 'processing',
            has_processing: true,
            version: { version_id: v.version_id, issue_key: v.issue_key },
          } : current);
          this.connectSSE(v.version_id);
          this.toastService.success('Pipeline started');
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

  viewVersion(version: UserStoryVersion): void {
    this.router.navigate(['/review', version.id], {
      queryParams: { issueKey: this.story()?.issue_key },
    });
  }

  viewLatestVersion(): void {
    const v = this.displayVersion();
    if (v) this.viewVersion(v);
  }

  // ─── Helpers ─────────────────────────────────────────────────────

  getAcList(story: UserStory): string[] {
    return (story.acceptance_criteria ?? []).filter(ac => ac && String(ac).trim());
  }

  formatScore(score: number | null | undefined): string {
    if (score == null || isNaN(score)) return '—';
    const display = score <= 1 ? score * 10 : score;
    return display.toFixed(1);
  }
}
