import { Component, OnInit, OnDestroy, signal, computed, inject, ViewChild } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { UserStory, UserStoryVersion, SSEEvent, PipelineResponse, StoryWithVersion, Project } from '../../models/user_story.model';
import { StoriesService, PipelineService, SseService, ToastService, VersionsService, ProjectsService } from '../../services';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { ImportModalComponent } from '../../components/import-modal/import-modal.component';
import { NavigationService } from '../../services/navigation.service';
import { InAppNotificationService } from '../../services/in-app-notification.service';

@Component({
  selector: 'app-user-stories',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    SpinnerComponent,
    ScoreBadgeComponent,
    SearchBarComponent,
    FilterBarComponent,
    PaginationComponent,
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
  private versionsService = inject(VersionsService);
  private toastService = inject(ToastService);
  private navigationService = inject(NavigationService);
  private projectsService = inject(ProjectsService);
  readonly notifService = inject(InAppNotificationService);
  
  @ViewChild('importModal') importModal!: ImportModalComponent;

  // ─── State ──────────────────────────────────────────────────────
  stories = signal<StoryWithVersion[]>([]);
  loading = signal(true);
  pipelineLoading = signal(false);

  // Pagination
  page = signal(1);
  pageSize = signal(10);

  // Projects list pour le filtre
projects = signal<{ id: string; project_name: string }[]>([]);
selectedProjectId = signal<string>('');

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

  // Rebuilt after stories load
  epicFilterGroup = signal<FilterGroup | null>(null);
  sprintFilterGroup = signal<FilterGroup | null>(null);

  // ─── Computed ───────────────────────────────────────────────────

  filteredStories = computed(() => {
    let result = this.stories();
    const query = this.searchQuery().toLowerCase().trim();
    const filters = this.activeFilters();

    if (query) {
      result = result.filter(story =>
        story.issue_key.toLowerCase().includes(query) ||
        (story.title?.toLowerCase().includes(query)) ||
        (story.description?.toLowerCase().includes(query))
      );
    }

    if (filters['priority']?.length) {
      result = result.filter(s =>
        filters['priority'].includes(s.priority?.toLowerCase() ?? '')
      );
    }

    if (filters['pipeline']?.length) {
      result = result.filter(s => {
        const status = this.getPipelineStatus(s);
        return filters['pipeline'].includes(status);
      });
    }

    if (filters['ac']?.length) {
      const wantAc = filters['ac'].includes('has_ac');
      const wantNoAc = filters['ac'].includes('no_ac');
      if (wantAc && !wantNoAc) {
        result = result.filter(s => this.getAcCount(s) > 0);
      } else if (wantNoAc && !wantAc) {
        result = result.filter(s => this.getAcCount(s) === 0);
      }
    }

  const selectedProjectId = filters['project']?.[0];
  if (selectedProjectId) {
    result = result.filter(s => s.project_id === selectedProjectId);
  }

  if (filters['epic']?.length) {
    result = result.filter(s => filters['epic'].includes(s.epic_name ?? ''));
  }

  if (filters['sprint']?.length) {
    result = result.filter(s => filters['sprint'].includes(s.sprint ?? ''));
  }

    return result;
  });

  paginatedStories = computed(() => {
    const all = this.filteredStories();
    const start = (this.page() - 1) * this.pageSize();
    return all.slice(start, start + this.pageSize());
  });

  selectedCount = computed(() => this.selectedKeys().size);

  /**
   * Set of issue_keys that need a visual indicator.
   * - ambiguous_story / quality_issue: always show (action required from PO, not just reading)
   * - other types: only when unread
   */
  storiesWithUnread = computed(() =>
    new Set(
      this.notifService.notifications()
        .filter(n =>
          n.issue_key && (
            n.type === 'ambiguous_story' ||
            n.type === 'quality_issue' ||
            !n.is_read
          )
        )
        .map(n => n.issue_key!)
    )
  );

  markStoryNotifsRead(issueKey: string, event: Event): void {
    event.stopPropagation();
    this.notifService.notifications()
      .filter(n => n.issue_key === issueKey && !n.is_read)
      .forEach(n => this.notifService.markRead(n.id));
  }

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

// user-stories.component.ts - ngOnInit
ngOnInit(): void {
    this.route.queryParams.subscribe(params => {
        this.projectId.set(params['projectId'] || null);
        this.projectName.set(params['projectName'] || null);
        const highlightKey = params['highlight'];
        const page = params['page'];

        if (page) {
            this.page.set(parseInt(page, 10));
        }

        // Ensure notification service is connected even after a page refresh
        const projectKey = params['projectKey'];
        if (projectKey && this.notifService.projectKey() !== projectKey) {
          this.notifService.connect(projectKey);
        }

        this.loadProjects();
        this.loadStories();
        
        if (highlightKey) {
            setTimeout(() => {
                this.scrollToStory(highlightKey);
            }, 800);  // ← Augmenter le délai
        }
    });
}

  ngOnDestroy(): void {
    console.log("[COMPONENT DESTROYED] cleaning up subscriptions");
    this.sseSubscriptions.forEach((sub) => {
      sub.unsubscribe();
    });
    this.sseSubscriptions.clear();
    this.versionsService.disconnectAllStreams();
  }
private rebuildDynamicFilters(stories: StoryWithVersion[]): void {
  // Epics
  const epicKeys = [...new Set(stories.map(s => s.epic_name).filter(Boolean) as string[])].sort();
  if (epicKeys.length > 0) {
    const epicGroup: FilterGroup = {
      key: 'epic',
      label: 'Epic',
      multiple: true,
      options: epicKeys.map(k => ({ value: k, label: k })),
    };
    const idx = this.filterGroups.findIndex(g => g.key === 'epic');
    if (idx !== -1) this.filterGroups[idx] = epicGroup;
    else this.filterGroups.push(epicGroup);
  } else {
    this.filterGroups = this.filterGroups.filter(g => g.key !== 'epic');
  }

  // Sprints
  const sprintNames = [...new Set(stories.map(s => s.sprint).filter(Boolean) as string[])].sort();
  if (sprintNames.length > 0) {
    const sprintGroup: FilterGroup = {
      key: 'sprint',
      label: 'Sprint',
      multiple: true,
      options: sprintNames.map(n => ({ value: n, label: n })),
    };
    const idx = this.filterGroups.findIndex(g => g.key === 'sprint');
    if (idx !== -1) this.filterGroups[idx] = sprintGroup;
    else this.filterGroups.push(sprintGroup);
  } else {
    this.filterGroups = this.filterGroups.filter(g => g.key !== 'sprint');
  }

  this.filterGroups = [...this.filterGroups];
}

loadProjects(): void {
  this.projectsService.getProjects().subscribe({
    next: (projects: Project[]) => {
      this.projects.set(projects);
      
      // Créer le filtre projet
      const projectOptions = projects.map(p => ({
        value: p.id,
        label: p.project_name,
      }));
      
      const projectFilter: FilterGroup = {
        key: 'project',
        label: 'Project',
        multiple: false,
        options: [
          { value: '', label: 'All Projects' },
          ...projectOptions
        ],
      };
      
      // Vérifier si le filtre projet existe déjà
      const existingIndex = this.filterGroups.findIndex(g => g.key === 'project');
      
      if (existingIndex !== -1) {
        // Remplacer
        this.filterGroups[existingIndex] = projectFilter;
      } else {
        // Ajouter au début
        this.filterGroups.unshift(projectFilter);
      }
      
      // ✅ Forcer la détection des changements (optionnel)
      this.filterGroups = [...this.filterGroups];
    },
    error: (err) => {
      console.error('Failed to load projects:', err);
    },
  });
}
onProjectChange(event: Event): void {
  const select = event.target as HTMLSelectElement;
  this.selectedProjectId.set(select.value);
  this.page.set(1);
}


// user-stories.component.ts
private scrollToStory(issueKey: string): void {
    // Attendre que le DOM soit complètement chargé
    setTimeout(() => {
        const element = document.getElementById(`story-${issueKey}`);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
            
            // Ajouter une classe de surbrillance
            element.classList.add('story-highlight');
            
            // Supprimer la classe après 3 secondes
            setTimeout(() => {
                element.classList.remove('story-highlight');
            }, 3000);
        } else {
            console.warn(`Element story-${issueKey} not found`);
        }
    }, 500);
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
        const storiesWithVersion: StoryWithVersion[] = stories.map(s => ({
          ...s,
          version: undefined,
          WorkflowStatus: undefined,
          versionScore: undefined,
          versionIteration: undefined,
          versions: [],
          has_processing: false,
          versions_count: 0,
        }));
        
        this.stories.set(storiesWithVersion);
        this.loading.set(false);
        this.rebuildDynamicFilters(storiesWithVersion);
        this.recoverVersionStates();
      },
      error: (err) => {
        console.error('Failed to load stories:', err);
        this.toastService.error('Failed to load stories');
        this.loading.set(false);
      },
    });
  }

  // ─── Recover version states after page load ─────────────────────
private recoverVersionStates(): void {
    const stories = this.stories();
    if (stories.length === 0) return;

    const issueKeys = stories.map(s => s.issue_key);

    this.versionsService.getVersionsByIssueKeys(issueKeys).subscribe({
        next: (versionsMap) => {
            
            this.stories.update(currentStories => {
                const updatedStories: StoryWithVersion[] = [];
                
                for (const s of currentStories) {
                    const versionData = versionsMap[s.issue_key];
                    
                    if (!versionData) {
                        updatedStories.push({
                            ...s,
                            WorkflowStatus: 'idle',
                            has_processing: false,
                        });
                        continue;
                    }

                    // ✅ CRÉER display_version CORRECTEMENT
                    const displayVersion: UserStoryVersion = {
                        id: versionData.version_id,
                        user_story_id: s.id,
                        improved_story: versionData.improved_story || s.description || '',
                        generated_acceptance_criteria: versionData.acceptance_criteria || [],
                        initial_score: versionData.initial_score || 0,
                        final_score: versionData.final_score || 0,
                        workflow_status: versionData.workflow_status || 'completed',
                        decision_status: versionData.decision_status || 'pending',
                        testability_score: versionData.testability_score,
                        is_testable: versionData.is_testable,
                        testability_issues: versionData.testability_issues || [],
                        started_at: versionData.started_at,
                        completed_at: versionData.completed_at,
                    };

                    const updated: StoryWithVersion = {
                        ...s,
                        version: {
                            version_id: versionData.version_id,
                            issue_key: s.issue_key,
                        },
                        WorkflowStatus: versionData.workflow_status,
                        versionScore: versionData.final_score,
                        has_processing: versionData.workflow_status === 'processing',
                        versions_count: versionData.versions_count || 0,
                        // ✅ TOUJOURS définir display_version
                        display_version: displayVersion,
                        latest_version: displayVersion,
                        // ✅ IMPORTANT: versions doit être un tableau
                        versions: [displayVersion],
                    };

                    if (versionData.decision_status === 'approved') {
                        updated.selected_version = displayVersion;
                    }

                    if (versionData.workflow_status === 'processing') {
                        this.reconnectSSE(s.issue_key, versionData.version_id);
                    }

                    updatedStories.push(updated);
                }

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

        this.stories.update(stories =>
          stories.map((s: StoryWithVersion) =>
            s.issue_key === issueKey
              ? {
                  ...s,
                  selected_version: updated.selected_version,
                  latest_version: updated.latest_version,
                  display_version: updated.selected_version ?? updated.latest_version,
                  processing_version: updated.processing_version,
                  has_processing: updated.has_processing || false,
                  versions_count: updated.versions_count || 0,
                  versions: updated.versions || [],
                }
              : s
          )
        );
      },
      error: (err) => console.error('[VERSIONS LOAD ERROR]', err)
    });
  }

  private reconnectSSE(issueKey: string, versionId: string): void {
    if (!this.versionsService.isVersionConnected(versionId) && !this.sseSubscriptions.has(versionId)) {
      console.log("[SSE RECONNECT]", issueKey, versionId);
      this.connectSSE(versionId, issueKey);
    }
  }

  // ─── Utils ──────────────────────────────────────────────────────

  isProcessing(story: StoryWithVersion): boolean {
    return story.WorkflowStatus === 'processing';
  }

getStatusLabel(story: StoryWithVersion): string {
    switch (story.WorkflowStatus) {
        case 'processing':
            return 'Processing...';
        case 'completed':
            return 'Completed';
        case 'failed':
            return 'Failed';
        case 'idle':
            return 'Not processed';
        default:
            return 'Not processed';
    }
}

  getDecisionStatus(story: StoryWithVersion): string {
    const version = this.getDisplayVersion(story);
    return version?.decision_status ?? 'pending';
  }

getDisplayVersion(story: StoryWithVersion): UserStoryVersion | null {
    // ✅ Priorité à selected_version
    if (story.selected_version) {
        return story.selected_version;
    }
    // ✅ Ensuite display_version (défini dans recoverVersionStates)
    if (story.display_version) {
        return story.display_version;
    }
    // ✅ Ensuite latest_version
    if (story.latest_version?.decision_status === 'rejected') {
        return story.latest_version;
    }
    return story.latest_version ?? null;
}

  getAcList(story: UserStory): string[] {
    const ac = story.acceptance_criteria;
    if (!ac) return [];
    return ac.filter(item => item && String(item).trim());
  }

  getAcCount(story: UserStory): number {
    return this.getAcList(story).length;
  }

  private getPipelineStatus(story: StoryWithVersion): string {
    if (story.WorkflowStatus === 'failed') return 'failed';
    if (story.WorkflowStatus === 'processing') return 'processing';
    if (story.display_version) return 'completed';
    return 'idle';
  }

  isCompleted(story: StoryWithVersion): boolean {
    if (story.WorkflowStatus === 'processing') return false;
    if (story.WorkflowStatus === 'failed') return true;
    return this.getDisplayVersion(story) !== null;
  }

  canRunPipeline(story: StoryWithVersion): boolean {
    if (story.WorkflowStatus === 'processing') return false;
    if (!story.version) return true;
    return ['completed', 'failed'].includes(story.WorkflowStatus ?? '');
  }

  canRerunPipeline(story: StoryWithVersion): boolean {
    if (story.WorkflowStatus === 'processing') return false;
    return this.getDisplayVersion(story) !== null && this.canRunPipeline(story);
  }

  // ─── Search & Filters ───────────────────────────────────────────

  onSearchChange(query: string): void {
    this.searchQuery.set(query);
    this.page.set(1);
  }

  onFiltersChange(filters: ActiveFilters): void {
    this.activeFilters.set(filters);
    this.page.set(1);
  }

  clearAllFilters(): void {
    this.searchQuery.set('');
    this.activeFilters.set({});
    this.selectedProjectId.set('');
    this.page.set(1);
  }

  // ─── Pagination ─────────────────────────────────────────────────

  onPageChange(p: number): void {
    this.page.set(p);
    this.navigationService.setCurrentPage(p);
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

  // ─── Detail page navigation ──────────────────────────────────────

  openStoryDetail(story: StoryWithVersion): void {
    const qp: Record<string, string | number> = { page: this.page() };
    const projectId = this.projectId();
    const projectName = this.projectName();
    if (projectId) qp['projectId'] = projectId;
    if (projectName) qp['projectName'] = projectName;

    this.router.navigate(['/user-stories', story.id], { queryParams: qp });
  }

  // ─── Selection ──────────────────────────────────────────────────

  isSelected(story: StoryWithVersion): boolean {
    return this.selectedKeys().has(story.issue_key);
  }

  toggleSelect(story: StoryWithVersion): void {
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

  // ─── Pipeline ───────────────────────────────────────────────────

  rerunPipeline(story: StoryWithVersion): void {
    this.runPipeline([story.issue_key]);
  }

  viewResults(story: StoryWithVersion): void {
    const version = this.getDisplayVersion(story);
    const versionId = story.version?.version_id || version?.id;
    
    if (!versionId) {
      console.error("❌ No version_id for review");
      this.toastService.error("No results available");
      return;
    }

    this.router.navigate(['/review', versionId], {
      queryParams: { issueKey: story.issue_key }
    });
  }

  runSinglePipeline(story: StoryWithVersion): void {
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

        if (response.versions && response.versions.length > 0) {
          response.versions.forEach(version => {
            this.disconnectVersion(version.version_id);

            this.stories.update(stories =>
              stories.map(s =>
                s.issue_key === version.issue_key
                  ? {
                      ...s,
                      display_version: undefined,
                      latest_version: undefined,
                      version: {
                        version_id: version.version_id,
                        issue_key: version.issue_key,
                      },
                      WorkflowStatus: 'processing',
                      versionIteration: 0,
                      versionScore: undefined,
                      has_processing: true,
                    }
                  : s
              )
            );
            
            this.connectSSE(version.version_id, version.issue_key);
          });

          const count = response.versions.length;
          const label = count === 1 ? 'user story' : 'user stories';
          this.toastService.success(`Pipeline started for ${count} ${label}`);

        } else {
          if (response.skipped?.length > 0) {
            const count = response.skipped.length;
            const label = count === 1 ? 'story' : 'stories';
            this.toastService.warning(
              `${count} ${label} skipped`,
              'No description found — product owner notified on Jira'
            );
          } else {
            this.toastService.warning('No stories to process');
          }
        }
      },
      error: (err) => {
        console.error('Pipeline error:', err);
        this.toastService.error('Failed to start pipeline');
        this.pipelineLoading.set(false);
      },
    });
  }

  // ─── SSE ────────────────────────────────────────────────────────

  private connectSSE(versionId: string, issueKey: string): void {
    if (this.sseSubscriptions.has(versionId)) {
      console.log("[SSE] Already subscribed to", versionId);
      return;
    }

    console.log("[CONNECT SSE]", versionId);

    const subscription = this.versionsService.connectToVersionStream(versionId).subscribe({
      next: (event) => this.handleSSEEvent(issueKey, event, versionId),
      error: (err) => {
        console.error(`[SSE] Error for ${issueKey}:`, err);
        this.sseSubscriptions.delete(versionId);
        
        setTimeout(() => {
          this.loadVersionState(versionId, issueKey);
        }, 1000);
      },
      complete: () => {
        console.log(`[SSE] Stream completed for ${issueKey}`);
        this.sseSubscriptions.delete(versionId);
      }
    });

    this.sseSubscriptions.set(versionId, subscription);
  }

  private handleSSEEvent(issueKey: string, event: SSEEvent, versionId: string): void {
    const data = event.data || {};

    console.log("[EVENT]", issueKey, event.type, data);

    switch (event.type) {
      case 'processing':
        this.stories.update(stories =>
          stories.map(s =>
            s.issue_key === issueKey
              ? {
                  ...s,
                  WorkflowStatus: 'processing',
                  has_processing: true,
                }
              : s
          )
        );
        break;

      case 'completed':
        this.stories.update(stories =>
          stories.map(s => {
            if (s.issue_key !== issueKey) return s;

            if (!data.version_id) {
              console.error("❌ Missing version_id", data);
              return s;
            }

            return {
              ...s,
              WorkflowStatus: 'completed',
              versionIteration: data.iteration ?? 1,
              versionScore: data.final_score,
              has_processing: false,
              display_version: {
                id: data.version_id,
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
                started_at: new Date().toISOString(),
                completed_at: new Date().toISOString(),
              },
            };
          })
        );
        
        // Recharger les versions pour avoir la liste à jour
        setTimeout(() => this.loadVersionsForStory(issueKey), 500);
        break;

      case 'failed':
        this.stories.update(stories =>
          stories.map(s =>
            s.issue_key === issueKey
              ? {
                  ...s,
                  WorkflowStatus: 'failed',
                  has_processing: false,
                }
              : s
          )
        );
        break;

      case 'defect_created': {
        const jiraKey = data.jira_issue_key;
        const msg = jiraKey
          ? `Defect reported automatically → Jira ${jiraKey}`
          : 'Defect saved locally (Jira not connected)';
        this.toastService.warning('⚠ Tech Lead: Defect Detected', msg);
        break;
      }
    }
  }

  private disconnectVersion(versionId: string): void {
    this.versionsService.disconnectFromVersionStream(versionId);
    const sub = this.sseSubscriptions.get(versionId);
    if (sub) {
      sub.unsubscribe();
      this.sseSubscriptions.delete(versionId);
    }
  }

  private loadVersionState(versionId: string, issueKey: string): void {
    this.versionsService.getVersion(versionId).subscribe({
      next: (state) => {
        console.log("[VERSION STATE]", issueKey, state);

        this.stories.update(stories =>
          stories.map(s => {
            if (s.issue_key !== issueKey) return s;

            if (state.workflow_status === 'completed') {
              return {
                ...s,
                version: { version_id: versionId, issue_key: issueKey },
                WorkflowStatus: 'completed',
                versionIteration: state.iteration ?? 0,
                versionScore: state.final_score,
                has_processing: false,
                display_version: {
                  id: versionId,
                  user_story_id: s.id,
                  improved_story: state.improved_story ?? '',
                  generated_acceptance_criteria: state.generated_acceptance_criteria ?? [],
                  initial_score: state.initial_score ?? 0,
                  final_score: state.final_score ?? 0,
                  workflow_status: 'completed',
                  decision_status: state.decision_status ?? 'pending',
                  testability_score: state.testability_score,
                  is_testable: state.is_testable,
                  testability_issues: state.testability_issues ?? [],
                  started_at: state.started_at,
                  completed_at: state.completed_at,
                },
              };
            }

            if (state.workflow_status === 'failed') {
              return {
                ...s,
                version: { version_id: versionId, issue_key: issueKey },
                WorkflowStatus: 'failed',
                has_processing: false,
              };
            }

            if (state.workflow_status === 'processing') {
              if (!this.versionsService.isVersionConnected(versionId) && !this.sseSubscriptions.has(versionId)) {
                this.connectSSE(versionId, issueKey);
              }
              return {
                ...s,
                version: { version_id: versionId, issue_key: issueKey },
                WorkflowStatus: 'processing',
                versionIteration: state.iteration ?? 0,
                has_processing: true,
              };
            }

            return s;
          })
        );
      },
      error: (err) => console.error("[VERSION STATE ERROR]", err)
    });
  }
}