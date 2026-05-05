import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { Subscription, firstValueFrom } from 'rxjs';
import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { AsyncJobResponse, TcCoverageRow, TestCaseService } from '../../services/test-case.service';
import { TestPlanService } from '../../services/test-plan.service';
import { StoriesService } from '../../services/stories.service';
import { SseService } from '../../services/sse.service';
import { ToastService } from '../../services/toast.service';
import { PlaywrightE2EService } from '../../services/playwright-e2e.service';
import { UserStory } from '../../models/user_story.model';
import { TestCaseStatus, Priority } from '../../models/test-case.model';
import { TestPlan } from '../../models/test-plan.model';
import { ConfirmDialogComponent } from '../../components/confirm-dialog/confirm-dialog.component';

// ── Display model avec toutes les correspondances ─────────────
interface TestCaseDisplay {
  id: string;
  tc_code: string;
  title: string;
  test_suite_id: string | null;
  test_suite_title: string | null;
  test_plan_id: string | null;
  test_plan_title: string | null;
  project_id: string | null;
  project_name: string | null;
  user_story_id: string | null;
  issue_key: string | null;
  user_story_title: string | null;
  sprint: string | null;
  epic_key: string | null;
  epic_name: string | null;
  tags: string[] | null;
  priority: string | null;
  test_type: string | null;
  execution_order: number | null;
  is_active: boolean;
}

export type GenJobStatus = 'queued' | 'processing' | 'generated' | 'failed';
export interface GenJob {
  us_id: string;
  issue_key: string;
  status: GenJobStatus;
  count?: number;
  error?: string;
}

@Component({
  selector: 'app-test-cases',
  standalone: true,
  imports: [CommonModule, FilterBarComponent, PaginationComponent, SearchBarComponent, SpinnerComponent, ConfirmDialogComponent],
  templateUrl: './test-cases.component.html',
  styleUrl: './test-cases.component.scss',
})
export class TestCasesComponent implements OnInit, OnDestroy {
  private testCaseService = inject(TestCaseService);
  private storiesService = inject(StoriesService);
  private testPlanService = inject(TestPlanService);
  private sseService = inject(SseService);
  private toastService = inject(ToastService);
  private playwrightService = inject(PlaywrightE2EService);
  private router = inject(Router);
  private sseSubscriptions = new Map<string, Subscription>();

  // =====================================================================
  // DATA
  // =====================================================================
  allTestCases = signal<TestCaseDisplay[]>([]);
  allStories = signal<UserStory[]>([]);
  testPlans = signal<TestPlan[]>([]);
  loading = signal(false);

  page = signal(1);
  pageSize = signal(6);


  // ── Confirm Dialog ──────────────────────────────────────────
showConfirmDialog = signal(false);
confirmDialogData = signal<{
  title: string;
  message: string;
  icon: string;
  confirmText: string;
  cancelText: string;
  variant: 'primary' | 'danger' | 'warning' | 'success';
  onConfirm: () => void;
}>({
  title: '',
  message: '',
  icon: '⚠️',
  confirmText: 'Confirm',
  cancelText: 'Cancel',
  variant: 'primary',
  onConfirm: () => {},
});
  // =====================================================================
  // FILTERS (simplifié : test_plan_id uniquement)
  // =====================================================================
  searchQuery = signal('');
  selectedTestPlanId = signal('');  // ✅ Filtre principal
  selectedStatus = signal('all');
  selectedPriorities = signal<string[]>([]);
  selectedTestTypes = signal<string[]>([]);
  selectedTags = signal<string[]>([]);
  activeFilters = signal<ActiveFilters>({});
  viewMode = signal<'cards' | 'table'>('cards');

  // =====================================================================
  // SELECTION
  // =====================================================================
  selectedTestCases = signal<Set<string>>(new Set());
  generatingIds = signal<Set<string>>(new Set());

  // =====================================================================
  // COVERAGE TABLE
  // =====================================================================
  coverageRows = signal<TcCoverageRow[]>([]);
  coveragePlanId = signal('');
  showCoverageTable = signal(false);
  coverageTableVisible = signal(true);
  coveragePage = signal(1);
  coveragePageSize = signal(5);

  paginatedCoverageRows = computed(() =>
    this.coverageRows().slice((this.coveragePage() - 1) * this.coveragePageSize(), this.coveragePage() * this.coveragePageSize())
  );
  totalCoveragePages = computed(() => Math.ceil(this.coverageRows().length / this.coveragePageSize()));
  totalCoverageItems = computed(() => this.coverageRows().length);

  toggleCoverageTable(): void { this.coverageTableVisible.update(v => !v); }

  loadCoverage(testPlanId: string): void {
    if (!testPlanId) { this.coverageRows.set([]); this.showCoverageTable.set(false); return; }
    this.coveragePlanId.set(testPlanId);
    this.testCaseService.getCoverageForPlan(testPlanId).subscribe({
      next: rows => { this.coverageRows.set(rows); this.showCoverageTable.set(true); this.coveragePage.set(1); },
      error: err => this.toastService.error('Failed to load coverage', err.message),
    });
  }

  onCoveragePageChange(p: number): void { this.coveragePage.set(p); }
  onCoveragePageSizeChange(s: number): void { this.coveragePageSize.set(s); this.coveragePage.set(1); }

  // =====================================================================
  // GENERATE PANEL (TestPlan uniquement)
  // =====================================================================
  showGenPanel = signal(false);
  genTestPlanId = signal('');
  genJobs = signal<GenJob[]>([]);
  isGenerating = signal(false);

  // ── COMPUTED ────────────────────────────────────────────────

  /** Tous les TestPlans disponibles */
  allTestPlans = computed(() => this.testPlans());

  availableTags = computed(() => {
    const seen = new Set<string>();
    for (const tc of this.allTestCases()) { for (const tag of tc.tags ?? []) seen.add(tag); }
    return Array.from(seen).sort();
  });

  filteredTestCases = computed(() => {
    let items = this.allTestCases();
    const q = this.searchQuery().toLowerCase();
    if (q) items = items.filter(tc => tc.tc_code.toLowerCase().includes(q) || tc.title.toLowerCase().includes(q) || (tc.issue_key ?? '').toLowerCase().includes(q));
    if (this.selectedTestPlanId()) items = items.filter(tc => tc.test_plan_id === this.selectedTestPlanId());
    if (this.selectedStatus() !== 'all') items = items.filter(tc => tc.is_active === (this.selectedStatus() === 'active'));
    if (this.selectedPriorities().length) items = items.filter(tc => this.selectedPriorities().includes((tc.priority || 'medium').toLowerCase()));
    if (this.selectedTestTypes().length) items = items.filter(tc => this.selectedTestTypes().includes((tc.test_type || '').toLowerCase()));
    if (this.selectedTags().length) items = items.filter(tc => this.selectedTags().every(tag => (tc.tags ?? []).includes(tag)));
    return items;
  });

  paginatedTestCases = computed(() => this.filteredTestCases().slice((this.page() - 1) * this.pageSize(), this.page() * this.pageSize()));
  totalFiltered = computed(() => this.filteredTestCases().length);
  totalPages = computed(() => Math.ceil(this.totalFiltered() / this.pageSize()));
  selectedCount = computed(() => this.selectedTestCases().size);
  allSelected = computed(() => this.paginatedTestCases().length > 0 && this.paginatedTestCases().every(tc => this.selectedTestCases().has(tc.id)));

  // Gen panel
  genTotalJobs = computed(() => this.genJobs().length);
  genCompletedJobs = computed(() => this.genJobs().filter(j => j.status === 'generated' || j.status === 'failed').length);
  genAllDone = computed(() => this.genTotalJobs() > 0 && this.genCompletedJobs() === this.genTotalJobs());

  // Progression fine par US
  genProgressTotal = signal(0);
  genProgressCurrent = signal(0);
  genCurrentUsKey = signal('');
  genProgress = computed(() => {
    if (this.genAllDone()) return 100;
    if (this.genProgressTotal() > 0) return Math.round((this.genProgressCurrent() / this.genProgressTotal()) * 100);
    return this.genTotalJobs() === 0 ? 0 : Math.round((this.genCompletedJobs() / this.genTotalJobs()) * 10); // 0-10% pendant init
  });

  filterGroups = computed<FilterGroup[]>(() => {
    const items = this.allTestCases();
    return [
      { key: 'status', label: 'Status', multiple: true, options: [
        { value: 'active', label: 'Active', count: items.filter(tc => tc.is_active).length },
        { value: 'archived', label: 'Archived', count: items.filter(tc => !tc.is_active).length },
      ]},
      { key: 'priority', label: 'Priority', multiple: true, options: [
        { value: 'critical', label: 'Critical', count: items.filter(tc => tc.priority === 'critical').length },
        { value: 'high', label: 'High', count: items.filter(tc => tc.priority === 'high').length },
        { value: 'medium', label: 'Medium', count: items.filter(tc => tc.priority === 'medium').length },
        { value: 'low', label: 'Low', count: items.filter(tc => tc.priority === 'low').length },
      ]},
      { key: 'test_type', label: 'Test Type', multiple: true, options: [
        { value: 'positive', label: 'Positive', count: items.filter(tc => tc.test_type === 'positive').length },
        { value: 'negative', label: 'Negative', count: items.filter(tc => tc.test_type === 'negative').length },
        { value: 'boundary', label: 'Boundary Value', count: items.filter(tc => tc.test_type === 'boundary').length },
      ].filter(o => o.count > 0)},
      ...(this.availableTags().length ? [{ key: 'tags', label: 'Tags', multiple: true, options: this.availableTags().map(tag => ({ value: tag, label: tag, count: items.filter(tc => (tc.tags ?? []).includes(tag)).length })) }] : []),
    ];
  });

  // =====================================================================
  // LIFECYCLE
  // =====================================================================
  ngOnInit(): void { this.loadTestPlans(); this.loadTestCases(); }
  ngOnDestroy(): void { this.sseSubscriptions.forEach(s => s.unsubscribe()); this.sseSubscriptions.clear(); }

  // =====================================================================
  // LOADERS
  // =====================================================================
  loadTestPlans(): void { this.testPlanService.getAll({ pageSize: 100, status: 'approved' }).subscribe({ next: res => this.testPlans.set(res.items) }); }

  loadTestCases(): void {
    this.loading.set(true);
    const filters: any = {};
    if (this.selectedTestPlanId()) filters.test_plan_id = this.selectedTestPlanId();
    if (this.searchQuery()) filters.search = this.searchQuery();
    if (this.selectedStatus() !== 'all') filters.status = [this.selectedStatus() as TestCaseStatus];
    if (this.selectedPriorities().length) filters.priority = this.selectedPriorities() as Priority[];

    this.testCaseService.getTestCases(filters).subscribe({
      next: (response: any[]) => {
        this.allTestCases.set(response.map((tc: any) => ({
          id: tc.id, tc_code: tc.tc_code, title: tc.title,
          test_suite_id: tc.test_suite_id ?? null, test_suite_title: tc.test_suite_title ?? null,
          test_plan_id: tc.test_plan_id ?? null, test_plan_title: tc.test_plan_title ?? null,
          project_id: tc.project_id ?? null, project_name: tc.project_name ?? null,
          // ✅ Correspondances automatiques du backend
          user_story_id: tc.user_story_id ?? null, issue_key: tc.issue_key ?? null,
          user_story_title: tc.user_story_title ?? null, sprint: tc.sprint ?? null,
          epic_key: tc.epic_key ?? null, epic_name: tc.epic_name ?? null,
          tags: tc.tags ?? null, priority: (tc.priority || 'medium').toLowerCase(),
          test_type: tc.test_type ?? null, execution_order: tc.execution_order ?? null,
          is_active: tc.is_active,
        })));
        this.loading.set(false); this.page.set(1);
      },
      error: err => { this.toastService.error('Failed to load test cases', err.message); this.loading.set(false); },
    });
  }

  // =====================================================================
  // FILTER HANDLERS (simplifié)
  // =====================================================================
  onTestPlanChange(event: Event): void { const id = (event.target as HTMLSelectElement).value; this.selectedTestPlanId.set(id); this.page.set(1); this.loadTestCases(); this.loadCoverage(id); }
  onStatusChange(event: Event): void { this.selectedStatus.set((event.target as HTMLSelectElement).value); this.page.set(1); }
  onSearchChange(query: string): void { this.searchQuery.set(query); this.page.set(1); }
  onFiltersChange(filters: ActiveFilters): void { this.activeFilters.set(filters); this.selectedStatus.set(filters['status']?.length ? filters['status'][0] : 'all'); this.selectedPriorities.set(filters['priority'] ?? []); this.selectedTestTypes.set(filters['test_type'] ?? []); this.selectedTags.set(filters['tags'] ?? []); this.page.set(1); }
  clearAllFilters(): void { this.searchQuery.set(''); this.selectedTestPlanId.set(''); this.selectedStatus.set('all'); this.selectedPriorities.set([]); this.selectedTestTypes.set([]); this.selectedTags.set([]); this.activeFilters.set({}); this.page.set(1); this.loadTestCases(); }
  refresh(): void { this.loadTestCases(); }

  // =====================================================================
  // GEN PANEL (TestPlan uniquement)
  // =====================================================================
  openGenPanel(): void { this.showGenPanel.set(true); this.genJobs.set([]); this.isGenerating.set(false); this.genProgressTotal.set(0); this.genProgressCurrent.set(0); this.genCurrentUsKey.set(''); }
  closeGenPanel(): void { if (this.isGenerating() && !this.genAllDone()) return; this.showGenPanel.set(false); this.genTestPlanId.set(''); this.genJobs.set([]); this.isGenerating.set(false); this.genProgressTotal.set(0); this.genProgressCurrent.set(0); this.genCurrentUsKey.set(''); }
  onGenTestPlanChange(event: Event): void { this.genTestPlanId.set((event.target as HTMLSelectElement).value); }

  genScenarioType = signal<'positive' | 'negative' | 'boundary'>('positive');

  readonly scenarioTypeOptions: { value: 'positive' | 'negative' | 'boundary'; label: string }[] = [
    { value: 'positive', label: '✅ Positive (happy path)' },
    { value: 'negative', label: '❌ Negative (error path)' },
    { value: 'boundary', label: '🔲 Boundary (limits)' },
  ];

  selectScenarioType(type: 'positive' | 'negative' | 'boundary'): void {
    this.genScenarioType.set(type);
  }

  startGeneration(): void {
    const testPlanId = this.genTestPlanId();
    if (!testPlanId || this.isGenerating()) return;

    this.isGenerating.set(true);
    const plan = this.testPlans().find(p => p.id === testPlanId);
    const jobs: GenJob[] = [{ us_id: testPlanId, issue_key: plan?.title ?? testPlanId, status: 'queued' }];
    this.genJobs.set(jobs);

    this.testCaseService.generateAsync(testPlanId, { test_suite_id: undefined, scenario_type: this.genScenarioType() }).subscribe({
      next: (r: AsyncJobResponse) => {
        this._updateJob(testPlanId, { status: 'processing' });
        this._subscribeToJobStream(testPlanId, r.job_id);
      },
      error: (e: any) => {
        this._updateJob(testPlanId, { status: 'failed', error: e.error?.detail ?? e.message });
        this._checkGenerationDone();
      },
    });
  }

  private _subscribeToJobStream(planId: string, jobId: string): void {
    const url = this.testCaseService.getStreamUrl(jobId);
    const sub = this.sseService.connectToStream<any>(url, jobId, ['tc_processing', 'tc_generated', 'tc_failed', 'tc_init', 'us_done', 'ping']).subscribe({
      next: (e) => {
        if (e.type === 'tc_processing') {
          this._updateJob(planId, { status: 'processing' });
        } else if (e.type === 'tc_init') {
          this.genProgressTotal.set(e.data.total_us);
          this.genProgressCurrent.set(0);
          this.genCurrentUsKey.set('');
        } else if (e.type === 'us_done') {
          this.genProgressCurrent.set(e.data.completed);
          this.genCurrentUsKey.set(e.data.issue_key ?? '');
        } else if (e.type === 'tc_generated') {
          this._updateJob(planId, { status: 'generated', count: e.data.count });
          sub.unsubscribe(); this.sseSubscriptions.delete(jobId); this._checkGenerationDone();
        } else if (e.type === 'tc_failed') {
          this._updateJob(planId, { status: 'failed', error: e.data.error });
          sub.unsubscribe(); this.sseSubscriptions.delete(jobId); this._checkGenerationDone();
        }
      },
      error: () => { this._updateJob(planId, { status: 'failed', error: 'SSE error' }); this.sseSubscriptions.delete(jobId); this._checkGenerationDone(); },
    });
    this.sseSubscriptions.set(jobId, sub);
  }
  private _updateJob(planId: string, patch: Partial<GenJob>): void { this.genJobs.update(j => j.map(j => j.us_id === planId ? { ...j, ...patch } : j)); }
  private _checkGenerationDone(): void { if (this.genAllDone()) { this.toastService.success('Generation complete'); this.loadTestCases(); if (this.genTestPlanId()) this.loadCoverage(this.genTestPlanId()); this.isGenerating.set(false); } }

  // =====================================================================
  // SELECTION / NAV
  // =====================================================================
  toggleSelect(tc: TestCaseDisplay): void { const s = new Set(this.selectedTestCases()); s.has(tc.id) ? s.delete(tc.id) : s.add(tc.id); this.selectedTestCases.set(s); }
  toggleSelectAll(): void { this.allSelected() ? this.selectedTestCases.set(new Set()) : this.selectedTestCases.set(new Set(this.paginatedTestCases().map(tc => tc.id))); }
bulkDelete(): void {
  const ids = Array.from(this.selectedTestCases());
  if (!ids.length) return;
  
  this.confirmDialogData.set({
    title: 'Delete Test Cases',
    message: `Delete ${ids.length} test case(s)?\n\nThis action cannot be undone.`,
    icon: '🗑️',
    confirmText: 'Delete',
    cancelText: 'Cancel',
    variant: 'danger',
    onConfirm: () => {
      this.loading.set(true);
      Promise.all(ids.map(id => firstValueFrom(this.testCaseService.deleteTestCase(id))))
        .then(() => {
          this.toastService.success('Deleted');
          this.selectedTestCases.set(new Set());
          this.loadTestCases();
        })
        .catch(e => {
          this.toastService.error('Delete failed', e.message);
          this.loading.set(false);
        });
    }
  });
  this.showConfirmDialog.set(true);
}
  viewTestCase(id: string, e?: Event): void { e?.stopPropagation(); this.router.navigate(['/test-cases', id]); }

deleteTestCase(id: string, e: Event): void {
  e.stopPropagation();
  
  this.confirmDialogData.set({
    title: 'Delete Test Case',
    message: 'Delete this test case?\n\nThis action cannot be undone.',
    icon: '🗑️',
    confirmText: 'Delete',
    cancelText: 'Cancel',
    variant: 'danger',
    onConfirm: () => {
      this.testCaseService.deleteTestCase(id).subscribe({
        next: () => {
          this.toastService.success('Deleted');
          this.loadTestCases();
        },
        error: err => this.toastService.error('Delete failed', err.message)
      });
    }
  });
  this.showConfirmDialog.set(true);
}

  generateScript(id: string, e: Event): void { e.stopPropagation(); const s = new Set(this.generatingIds()); s.add(id); this.generatingIds.set(s); this.playwrightService.generateScript({ test_case_id: id }).subscribe({ next: res => { const u = new Set(this.generatingIds()); u.delete(id); this.generatingIds.set(u); if (res.status === 'generated') { this.toastService.success('Script generated'); this.router.navigate(['/playwright-scripts']); } }, error: err => { const u = new Set(this.generatingIds()); u.delete(id); this.generatingIds.set(u); this.toastService.error('Generation failed', err.message); } }); }
  onPageChange(p: number): void { this.page.set(p); }
  onPageSizeChange(s: number): void { this.pageSize.set(s); this.page.set(1); }
  getPriorityClass(p: string | null): string { return { critical: 'priority-critical', high: 'priority-high', medium: 'priority-medium', low: 'priority-low' }[p || 'medium'] ?? 'priority-medium'; }
  getStatusLabel(a: boolean): string { return a ? 'Active' : 'Archived'; }
  setViewMode(m: 'cards' | 'table'): void { this.viewMode.set(m); }
  getJobStatusClass(s: GenJobStatus): string { return { queued: 'job-queued', processing: 'job-processing', generated: 'job-generated', failed: 'job-failed' }[s]; }
  getTagClass(tag: string): string { return { positive: 'tag-positive', smoke: 'tag-smoke', regression: 'tag-regression', negative: 'tag-negative' }[tag] ?? 'tag-default'; }
getTestTypeClass(t: string | null): string {
  return {
    'positive': 'type-positive',
    'negative': 'type-negative',
    'boundary': 'type-boundary',
    'boundary_value': 'type-boundary',
  }[t?.toLowerCase() ?? ''] ?? 'type-default';
}}