import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Subscription } from 'rxjs';

import { PlaywrightE2EService } from '../../services/playwright-e2e.service';
import { TestCaseService } from '../../services/test-case.service';
import { ProjectsService } from '../../services/projects.service';
import { ToastService } from '../../services/toast.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { FilterBarComponent, FilterGroup, ActiveFilters } from '../../components/filter-bar/filter-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';

import { TestCase } from '../../models/test-case.model';
import { Project } from '../../models/user_story.model';
import {
  ScriptInfo,
  ExecutionStep,
  TestResultStatus,
} from '../../models/playwright.models';

interface TestCaseScriptRow {
  testCase: TestCase;
  hasScript: boolean;
  activeScriptId: string | null;
  activeScriptVersion: number | null;
  placeholderCount: number;
  lastRunStatus: string | null;
  isGenerating: boolean;
  isRunning: boolean;
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
  private testCaseService = inject(TestCaseService);
  private projectsService = inject(ProjectsService);
  private toastService = inject(ToastService);
  private router = inject(Router);

  rows = signal<TestCaseScriptRow[]>([]);
  projects = signal<Project[]>([]);
  isLoading = signal(false);

  // Execution config
  appUrl = signal('');
  browser = signal<'chromium' | 'firefox' | 'webkit'>('chromium');
  headless = signal(true);

  // Active execution
  activeTestCaseId = signal<string | null>(null);
  executionSteps = signal<ExecutionStep[]>([]);

  // Filters
  searchQuery = signal('');
  selectedProjectId = signal<string>('');
  activeFilters = signal<ActiveFilters>({});

  // Pagination
  page = signal(1);
  pageSize = signal(6);

  private stepsSub: Subscription | null = null;
  private executingSub: Subscription | null = null;

  readonly browsers: ('chromium' | 'firefox' | 'webkit')[] = ['chromium', 'firefox', 'webkit'];

  // ===== COMPUTED =====

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

    return items;
  });

  paginatedRows = computed(() => {
    const start = (this.page() - 1) * this.pageSize();
    return this.filteredRows().slice(start, start + this.pageSize());
  });

  totalFiltered = computed(() => this.filteredRows().length);
  totalPages = computed(() => Math.ceil(this.totalFiltered() / this.pageSize()));

  totalScripts = computed(() => this.rows().filter(r => r.hasScript).length);
  totalRows = computed(() => this.rows().length);

  filterGroups = computed<FilterGroup[]>(() => {
    const items = this.rows();
    return [
      {
        key: 'script',
        label: 'Script',
        multiple: false,
        options: [
          { value: 'has_script', label: 'Has Script', count: items.filter(r => r.hasScript).length },
          { value: 'no_script', label: 'No Script', count: items.filter(r => !r.hasScript).length },
        ],
      },
      {
        key: 'run_status',
        label: 'Last Run',
        multiple: true,
        options: [
          { value: 'passed', label: 'Passed', count: items.filter(r => r.lastRunStatus === 'passed').length },
          { value: 'failed', label: 'Failed', count: items.filter(r => r.lastRunStatus === 'failed').length },
          { value: 'error', label: 'Error', count: items.filter(r => r.lastRunStatus === 'error').length },
          { value: 'not_run', label: 'Not Run', count: items.filter(r => !r.lastRunStatus).length },
        ],
      },
    ];
  });

  // ===== LIFECYCLE =====

  ngOnInit(): void {
    this.loadProjects();
    this.loadData();

    this.stepsSub = this.playwrightService.executionSteps$.subscribe(steps => {
      this.executionSteps.set(steps);
    });
  }

  ngOnDestroy(): void {
    this.stepsSub?.unsubscribe();
    this.executingSub?.unsubscribe();
    this.playwrightService.stopStreaming();
  }

  // ===== DATA =====

  private loadProjects(): void {
    this.projectsService.getProjects().subscribe({
      next: (projects) => this.projects.set(projects),
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
      isRunning: false,
    }));
    this.rows.set(rows);
    this.isLoading.set(false);

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

          if (info.activeScriptId) {
            this.loadLastRun(tc.id);
          }
        },
        error: () => {},
      });
    });
  }

  private loadLastRun(testCaseId: string): void {
    this.playwrightService.getLastRun(testCaseId).subscribe({
      next: (run) => {
        if (run.result?.status) {
          this.updateRow(testCaseId, { lastRunStatus: run.result!.status ?? null });
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

  // ===== FILTERS =====

  onSearchChange(query: string): void {
    this.searchQuery.set(query);
    this.page.set(1);
  }

  onProjectChange(event: Event): void {
    this.selectedProjectId.set((event.target as HTMLSelectElement).value);
    this.page.set(1);
  }

  onFiltersChange(filters: ActiveFilters): void {
    this.activeFilters.set(filters);
    this.page.set(1);
  }

  clearAllFilters(): void {
    this.searchQuery.set('');
    this.selectedProjectId.set('');
    this.activeFilters.set({});
    this.page.set(1);
  }

  // ===== PAGINATION =====

  onPageChange(p: number): void {
    this.page.set(p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  onPageSizeChange(size: number): void {
    this.pageSize.set(size);
    this.page.set(1);
  }

  // ===== ACTIONS =====

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
          this.toastService.success(`Script v${res.version_number} generated (${res.placeholder_count} placeholders)`);
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

  runFullWorkflow(row: TestCaseScriptRow): void {
    this.updateRow(row.testCase.id, { isRunning: true });
    this.activeTestCaseId.set(row.testCase.id);
    this.playwrightService.reset();

    this.playwrightService.runFullWorkflowWithStream({
      test_case_id: row.testCase.id,
      app_url: this.appUrl() || undefined,
      browser: this.browser(),
      headless: this.headless(),
    });

    this.executingSub = this.playwrightService.isExecuting$.subscribe(executing => {
      if (!executing) {
        this.updateRow(row.testCase.id, { isRunning: false });
        this.loadLastRun(row.testCase.id);
        this.executingSub?.unsubscribe();
      }
    });
  }

  executeOnly(row: TestCaseScriptRow): void {
    if (!row.activeScriptId) return;
    this.updateRow(row.testCase.id, { isRunning: true });
    this.activeTestCaseId.set(row.testCase.id);
    this.playwrightService.reset();

    this.playwrightService.executeScriptWithStream({
      test_case_id: row.testCase.id,
      script_version_id: row.activeScriptId,
      app_url: this.appUrl() || undefined,
      browser: this.browser(),
      headless: this.headless(),
    });

    this.executingSub = this.playwrightService.isExecuting$.subscribe(executing => {
      if (!executing) {
        this.updateRow(row.testCase.id, { isRunning: false });
        this.loadLastRun(row.testCase.id);
        this.executingSub?.unsubscribe();
      }
    });
  }

  goToDetail(testCaseId: string): void {
    this.router.navigate(['/playwright-scripts', testCaseId]);
  }

  isActiveTestCase(testCaseId: string): boolean {
    return this.activeTestCaseId() === testCaseId;
  }

  getStepIcon(type: string): string {
    switch (type) {
      case 'think': return '🧠';
      case 'act': return '⚡';
      case 'observe': return '👁️';
      default: return '•';
    }
  }

  getRunStatusClass(status: string | null): string {
    switch (status) {
      case TestResultStatus.PASSED: return 'badge-success';
      case TestResultStatus.FAILED: return 'badge-danger';
      case TestResultStatus.ERROR: return 'badge-warning';
      default: return 'badge-secondary';
    }
  }

  getAccentClass(status: string | null): string {
    switch (status) {
      case 'passed': return 'accent-passed';
      case 'failed': return 'accent-failed';
      case 'error': return 'accent-error';
      default: return 'accent-none';
    }
  }
}
