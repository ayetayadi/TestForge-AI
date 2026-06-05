import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';

import { PlaywrightE2EService } from '../../services/playwright-e2e.service';
import { TestCaseService } from '../../services/test-case.service';
import { TestSuiteService } from '../../services/test-suite.service';
import { ProjectsService } from '../../services/projects.service';
import { ToastService } from '../../services/toast.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';

import { TestCase } from '../../models/test-case.model';
import { Project } from '../../models/user_story.model';
import { TestSuiteListItem } from '../../models/test-suite.model';
import { ScriptInfo, ExecutionStep, TestResultStatus } from '../../models/playwright.models';

// ── Row in the scripts grid ────────────────────────────────────────────────────
interface TestCaseScriptRow {
  testCase: TestCase;
  hasScript: boolean;
  activeScriptId: string | null;
  activeScriptVersion: number | null;
  placeholderCount: number;
  lastRunStatus: string | null;
  isGenerating: boolean;
}

@Component({
  selector: 'app-playwright-scripts',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    SpinnerComponent,
    SearchBarComponent,
    FilterBarComponent,
    PaginationComponent,
  ],
  templateUrl: './playwright-scripts.component.html',
  styleUrls: ['./playwright-scripts.component.scss'],
})
export class PlaywrightScriptsComponent implements OnInit, OnDestroy {
  private playwrightService = inject(PlaywrightE2EService);
  private testCaseService   = inject(TestCaseService);
  private testSuiteService  = inject(TestSuiteService);
  private projectsService   = inject(ProjectsService);
  private toastService      = inject(ToastService);
  private router            = inject(Router);

  // ── Script grid ──────────────────────────────────────────────────────────────
  rows      = signal<TestCaseScriptRow[]>([]);
  projects  = signal<Project[]>([]);
  isLoading = signal(false);

  showDeleteConfirm = signal(false);
  pendingDeleteId   = signal<string | null>(null);
  tcOrderMap        = signal<Map<string, number>>(new Map());

  activeTestCaseId = signal<string | null>(null);
  executionSteps   = signal<ExecutionStep[]>([]);

  // ── Filters ───────────────────────────────────────────────────────────────────
  searchQuery         = signal('');
  selectedProjectId   = signal<string>('');
  selectedSuiteFilter = signal<string>('');
  activeFilters       = signal<ActiveFilters>({});

  // ── Pagination ────────────────────────────────────────────────────────────────
  page     = signal(1);
  pageSize = signal(6);

  // ── Suites list (for filter) ─────────────────────────────────────────────────
  suites = signal<TestSuiteListItem[]>([]);

  private stepsSub: Subscription | null = null;

  // ── Computed: filtered + paginated rows ──────────────────────────────────────
  filteredRows = computed(() => {
    let items = this.rows();

    const search = this.searchQuery().toLowerCase();
    if (search) {
      items = items.filter(r =>
        r.testCase.tc_code.toLowerCase().includes(search) ||
        r.testCase.title.toLowerCase().includes(search) ||
        (r.testCase.issue_key?.toLowerCase().includes(search) ?? false)
      );
    }

    const projectId = this.selectedProjectId();
    if (projectId) {
      const project = this.projects().find(p => p.id === projectId);
      if (project) {
        items = items.filter(r => r.testCase.project_name === project.project_name);
      }
    }

    const suiteFilter = this.selectedSuiteFilter();
    if (suiteFilter) {
      items = items.filter(r => r.testCase.test_suite_id === suiteFilter);
    }

    const filters = this.activeFilters();

    const scriptFilter = filters['script'];
    if (scriptFilter?.length) {
      items = items.filter(r =>
        scriptFilter.some(f =>
          (f === 'has_script' && r.hasScript) || (f === 'no_script' && !r.hasScript)
        )
      );
    }

    const runFilter = filters['run_status'];
    if (runFilter?.length) {
      items = items.filter(r =>
        runFilter.some(f => {
          if (f === 'not_run') return !r.lastRunStatus;
          return r.lastRunStatus === f;
        })
      );
    }

    const typeFilter = filters['test_type'];
    if (typeFilter?.length) {
      items = items.filter(r =>
        typeFilter.some(f => r.testCase.test_type === f)
      );
    }

    const orderMap = this.tcOrderMap();
    items = [...items].sort((a, b) => {
      const oa = orderMap.get(a.testCase.tc_code) ?? Infinity;
      const ob = orderMap.get(b.testCase.tc_code) ?? Infinity;
      return oa - ob;
    });

    return items;
  });

  paginatedRows = computed(() => {
    const start = (this.page() - 1) * this.pageSize();
    return this.filteredRows().slice(start, start + this.pageSize());
  });

  totalFiltered = computed(() => this.filteredRows().length);
  totalPages    = computed(() => Math.ceil(this.totalFiltered() / this.pageSize()));
  totalScripts  = computed(() => this.rows().filter(r => r.hasScript).length);
  totalRows     = computed(() => this.rows().length);

  filterGroups = computed<FilterGroup[]>(() => {
    const items = this.rows();
    return [
      {
        key: 'script',
        label: 'Script',
        multiple: false,
        options: [
          { value: 'has_script', label: 'Has Script', count: items.filter(r => r.hasScript).length },
          { value: 'no_script',  label: 'No Script',  count: items.filter(r => !r.hasScript).length },
        ],
      },
      {
        key: 'run_status',
        label: 'Last Run',
        multiple: true,
        options: [
          { value: 'passed',  label: 'Passed',  count: items.filter(r => r.lastRunStatus === 'passed').length },
          { value: 'failed',  label: 'Failed',  count: items.filter(r => r.lastRunStatus === 'failed').length },
          { value: 'error',   label: 'Error',   count: items.filter(r => r.lastRunStatus === 'error').length },
          { value: 'not_run', label: 'Not Run', count: items.filter(r => !r.lastRunStatus).length },
        ],
      },
      {
        key: 'test_type',
        label: 'Test Type',
        multiple: true,
        options: [
          { value: 'positive',  label: 'Positive',  count: items.filter(r => r.testCase.test_type === 'positive').length },
          { value: 'negative',  label: 'Negative',  count: items.filter(r => r.testCase.test_type === 'negative').length },
          { value: 'boundary',  label: 'Boundary',  count: items.filter(r => r.testCase.test_type === 'boundary').length },
        ],
      },
    ];
  });

  // ── Lifecycle ─────────────────────────────────────────────────────────────────
  ngOnInit(): void {
    this.loadProjects();
    this.loadSuites();
    this.loadData();

    this.stepsSub = this.playwrightService.executionSteps$.subscribe(steps => {
      this.executionSteps.set(steps);
    });
  }

  ngOnDestroy(): void {
    this.stepsSub?.unsubscribe();
    this.playwrightService.stopStreaming();
  }

  // ── Data loading ──────────────────────────────────────────────────────────────
  private loadProjects(): void {
    this.projectsService.getProjects().subscribe({
      next: (projects) => this.projects.set(projects),
      error: () => {},
    });
  }

  private loadSuites(): void {
    this.testSuiteService.getAll({ status: 'active' }).subscribe({
      next: (res) => this.suites.set(res.items),
      error: () => {},
    });
  }

  loadData(): void {
    this.isLoading.set(true);
    this.testCaseService.getTestCases().subscribe({
      next: (testCases) => this.loadScriptInfoForAll(testCases),
      error: () => {
        this.toastService.error('Error loading test cases');
        this.isLoading.set(false);
      },
    });
  }

  private loadScriptInfoForAll(testCases: TestCase[]): void {
    const rows: TestCaseScriptRow[] = testCases.map(tc => ({
      testCase: tc,
      hasScript: false,
      activeScriptId: null,
      activeScriptVersion: null,
      placeholderCount: 0,
      lastRunStatus: null,
      isGenerating: false,
    }));
    this.rows.set(rows);
    this.isLoading.set(false);
    this.loadDependencyOrders(testCases);
    testCases.forEach((tc) => {
      this.playwrightService.getScriptInfo(tc.id).subscribe({
        next: (info) => {
          const activeScript = info.scripts.find((s: ScriptInfo) => s.is_active);
          this.updateRow(tc.id, {
            hasScript: info.hasScript,
            activeScriptId: info.activeScriptId ?? null,
            activeScriptVersion: info.activeScriptVersion ?? null,
            placeholderCount: activeScript?.placeholder_count ?? 0,
          });
          if (info.activeScriptId) this.loadLastRun(tc.id);
        },
        error: () => {},
      });
    });
  }

  private loadDependencyOrders(testCases: TestCase[]): void {
    const planIds = [...new Set(
      testCases.map(tc => tc.test_plan_id).filter((id): id is string => !!id)
    )];
    if (planIds.length === 0) return;

    forkJoin(
      planIds.map(planId =>
        this.testSuiteService.getDependencyGraph(planId).pipe(
          catchError(() => of({ nodes: [], edges: [], execution_order: [] as string[] }))
        )
      )
    ).subscribe(graphs => {
      const orderMap = new Map<string, number>();
      let pos = 1;
      graphs.forEach(graph => {
        (graph.execution_order as string[]).forEach(code => { orderMap.set(code, pos++); });
      });
      this.tcOrderMap.set(orderMap);
    });
  }

  private loadLastRun(testCaseId: string): void {
    this.playwrightService.getLastRun(testCaseId).subscribe({
      next: (run: any) => {
        const status = run?.tc_result?.status ?? null;
        if (status) {
          this.updateRow(testCaseId, { lastRunStatus: status });
        }
      },
      error: () => {},
    });
  }

  private updateRow(id: string, updates: Partial<TestCaseScriptRow>): void {
    this.rows.update(prev => prev.map(r =>
      r.testCase.id === id ? { ...r, ...updates } : r
    ));
  }

  // ── Filters ───────────────────────────────────────────────────────────────────
  onSearchChange(query: string): void { this.searchQuery.set(query); this.page.set(1); }
  onProjectChange(event: Event): void {
    this.selectedProjectId.set((event.target as HTMLSelectElement).value);
    this.page.set(1);
  }
  onSuiteFilterChange(event: Event): void {
    this.selectedSuiteFilter.set((event.target as HTMLSelectElement).value);
    this.page.set(1);
  }
  onFiltersChange(filters: ActiveFilters): void { this.activeFilters.set(filters); this.page.set(1); }
  clearAllFilters(): void {
    this.searchQuery.set('');
    this.selectedProjectId.set('');
    this.selectedSuiteFilter.set('');
    this.activeFilters.set({});
    this.page.set(1);
  }

  // ── Pagination ────────────────────────────────────────────────────────────────
  onPageChange(p: number): void { this.page.set(p); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  onPageSizeChange(size: number): void { this.pageSize.set(size); this.page.set(1); }

  // ── Script grid actions ───────────────────────────────────────────────────────
  generateScript(row: TestCaseScriptRow): void {
    this.updateRow(row.testCase.id, { isGenerating: true });
    this.activeTestCaseId.set(row.testCase.id);
    this.playwrightService.reset();

    this.playwrightService.generateScript({ test_case_id: row.testCase.id }).subscribe({
      next: (res) => {
        this.updateRow(row.testCase.id, {
          isGenerating: false,
          hasScript: res.status === 'generated',
          activeScriptId: res.script_version_id ?? row.activeScriptId,
          activeScriptVersion: res.version_number ?? row.activeScriptVersion,
          placeholderCount: res.placeholder_count,
        });
        if (res.status === 'generated') {
          this.toastService.success(`v1 Draft generated (${res.placeholder_count} placeholder${res.placeholder_count !== 1 ? 's' : ''})`);
        } else {
          this.toastService.error(res.error ?? 'Generation failed');
        }
      },
      error: (err) => {
        this.updateRow(row.testCase.id, { isGenerating: false });
        this.toastService.error(err.message);
      },
    });
  }

  goToDetail(testCaseId: string): void {
    this.router.navigate(['/playwright-scripts', testCaseId]);
  }

  isActiveTestCase(testCaseId: string): boolean {
    return this.activeTestCaseId() === testCaseId;
  }

  requestDeleteAllScripts(testCaseId: string): void {
    this.pendingDeleteId.set(testCaseId);
    this.showDeleteConfirm.set(true);
  }

  confirmDeleteAllScripts(): void {
    const id = this.pendingDeleteId();
    if (!id) return;
    this.showDeleteConfirm.set(false);
    this.playwrightService.deleteAllScripts(id).subscribe({
      next: (res) => {
        this.pendingDeleteId.set(null);
        this.toastService.success(`Deleted ${res.count} script version(s)`);
        this.updateRow(id, {
          hasScript: false, activeScriptId: null, activeScriptVersion: null,
          placeholderCount: 0, lastRunStatus: null,
        });
      },
      error: (err) => {
        this.pendingDeleteId.set(null);
        this.toastService.error(err?.error?.detail ?? 'Failed to delete scripts');
      },
    });
  }

  cancelDeleteAllScripts(): void {
    this.showDeleteConfirm.set(false);
    this.pendingDeleteId.set(null);
  }

  // ── UI helpers ────────────────────────────────────────────────────────────────
  getStepIcon(type: string): string {
    switch (type) {
      case 'think': return '🧠';
      case 'act':   return '⚡';
      case 'observe': return '👁️';
      default: return '•';
    }
  }

  getTestTypeBadgeClass(type: string | null): string {
    switch (type) {
      case 'positive':  return 'badge-type-positive';
      case 'negative':  return 'badge-type-negative';
      case 'boundary':  return 'badge-type-boundary';
      default:          return 'badge-secondary';
    }
  }

  getRunStatusClass(status: string | null): string {
    switch (status) {
      case TestResultStatus.PASSED: return 'badge-success';
      case TestResultStatus.FAILED: return 'badge-danger';
      case TestResultStatus.ERROR:  return 'badge-warning';
      default: return 'badge-secondary';
    }
  }

  getAccentClass(status: string | null): string {
    switch (status) {
      case 'passed': return 'accent-passed';
      case 'failed': return 'accent-failed';
      case 'error':  return 'accent-error';
      default: return 'accent-none';
    }
  }
}
