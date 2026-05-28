import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { DragDropModule, CdkDragDrop, moveItemInArray } from '@angular/cdk/drag-drop';

import {
  PlaywrightE2EService, SuiteSSEEvent, SuiteScriptStatus, AvailableModel,
} from '../../services/playwright-e2e.service';
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
  isRunning: boolean;
}

// ── Row inside the suite-run modal ────────────────────────────────────────────
interface ModalTcRow {
  id: string;
  tc_code: string;
  title: string;
  execution_order: number | null;
  excluded: boolean;
  has_script: boolean;
  placeholder_count: number;
  source?: string;
}

// ── Live execution log entry ──────────────────────────────────────────────────
interface SuiteLogEntry {
  tc_id: string;
  tc_code: string;
  title: string;
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped';
  run_id?: string;
}

@Component({
  selector: 'app-playwright-scripts',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    RouterLink,
    DragDropModule,
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
  searchQuery        = signal('');
  selectedProjectId  = signal<string>('');
  selectedSuiteFilter = signal<string>('');
  activeFilters      = signal<ActiveFilters>({});

  // ── Pagination ────────────────────────────────────────────────────────────────
  page     = signal(1);
  pageSize = signal(6);

  // ── Suites list (for filter + modal) ─────────────────────────────────────────
  suites = signal<TestSuiteListItem[]>([]);

  // ── Suite Run Modal ───────────────────────────────────────────────────────────
  showRunModal        = signal(false);
  runModalStep        = signal<1 | 2>(1);
  runModalSuiteId     = signal<string>('');
  runModalAppUrl      = signal('');
  runModalBrowser     = signal<'chromium' | 'firefox' | 'webkit'>('chromium');
  runModalHeadless    = signal(true);
  runModalStopOnFail  = signal(false);
  runModalModel       = signal('llama-3.3-70b-versatile');
  runModalTcs         = signal<ModalTcRow[]>([]);
  isLoadingModalTcs   = signal(false);
  isSavingOrder       = signal(false);
  availableModels     = signal<AvailableModel[]>([]);

  runModalSuiteName = computed(() =>
    this.suites().find(s => s.id === this.runModalSuiteId())?.title ?? ''
  );

  runModalModelDescription = computed(() =>
    this.availableModels().find(m => m.id === this.runModalModel())?.description ?? ''
  );

  modalErrors = computed<string[]>(() => {
    const errors: string[] = [];
    const tcs = this.runModalTcs().filter(t => !t.excluded);
    if (tcs.length === 0) errors.push('At least one test case must be included.');
    if (!this.runModalAppUrl().trim()) errors.push('App URL is required.');
    return errors;
  });

  // ── Live Execution Panel ──────────────────────────────────────────────────────
  isSuiteRunning    = signal(false);
  showSuitePanel    = signal(false);
  suiteLogEntries   = signal<SuiteLogEntry[]>([]);
  suiteRunSummary   = signal<{ total: number; passed: number; failed: number; skipped: number; duration: number } | null>(null);
  suiteRunningName  = signal('');
  isDownloadingReport = signal(false);

  // ── Email Dialog (suite report) ───────────────────────────────────────────────
  showEmailDialog = signal(false);
  emailTo         = signal('');
  isSendingEmail  = signal(false);

  private stepsSub:     Subscription | null = null;
  private executingSub: Subscription | null = null;
  private suiteSub:     Subscription | null = null;

  readonly browsers: ('chromium' | 'firefox' | 'webkit')[] = ['chromium', 'firefox', 'webkit'];

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

    const orderMap = this.tcOrderMap();
    items = [...items].sort((a, b) => {
      const oa = orderMap.get(a.testCase.tc_code) ?? Infinity;
      const ob = orderMap.get(b.testCase.tc_code) ?? Infinity;
      return oa - ob;
    });

    return items;
  });

  paginatedRows  = computed(() => {
    const start = (this.page() - 1) * this.pageSize();
    return this.filteredRows().slice(start, start + this.pageSize());
  });

  totalFiltered = computed(() => this.filteredRows().length);
  totalPages    = computed(() => Math.ceil(this.totalFiltered() / this.pageSize()));
  totalScripts  = computed(() => this.rows().filter(r => r.hasScript).length);
  totalRows     = computed(() => this.rows().length);
  hasFailedRuns = computed(() => this.suiteLogEntries().some(e => e.status === 'failed' && e.run_id));

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
    ];
  });

  // ── Lifecycle ─────────────────────────────────────────────────────────────────
  ngOnInit(): void {
    this.loadProjects();
    this.loadSuites();
    this.loadData();
    this.loadAvailableModels();

    this.stepsSub = this.playwrightService.executionSteps$.subscribe(steps => {
      this.executionSteps.set(steps);
    });
  }

  ngOnDestroy(): void {
    this.stepsSub?.unsubscribe();
    this.executingSub?.unsubscribe();
    this.suiteSub?.unsubscribe();
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

  private loadAvailableModels(): void {
    this.playwrightService.getAvailableModels().subscribe({
      next: (res) => {
        this.availableModels.set(res.models);
        const def = res.models.find(m => m.is_default);
        if (def) this.runModalModel.set(def.id);
      },
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

  // ── Suite Run Modal ───────────────────────────────────────────────────────────
  openRunModal(): void {
    this.runModalStep.set(1);
    this.runModalSuiteId.set('');
    this.runModalAppUrl.set('');
    this.runModalBrowser.set('chromium');
    this.runModalHeadless.set(true);
    this.runModalStopOnFail.set(false);
    this.runModalTcs.set([]);
    this.showRunModal.set(true);
  }

  closeRunModal(): void {
    this.showRunModal.set(false);
    this.runModalStep.set(1);
  }

  proceedToStep2(): void {
    const suiteId = this.runModalSuiteId();
    if (!suiteId) { this.toastService.error('Please select a test suite'); return; }
    if (!this.runModalAppUrl().trim()) { this.toastService.error('App URL is required'); return; }

    this.isLoadingModalTcs.set(true);

    forkJoin({
      suite: this.testSuiteService.getById(suiteId),
      scripts: this.playwrightService.getSuiteScriptsStatus(suiteId).pipe(
        catchError(() => of({ suite_id: suiteId, test_cases: [] as SuiteScriptStatus[], total: 0 }))
      ),
    }).subscribe({
      next: ({ suite, scripts }) => {
        const scriptMap = new Map(scripts.test_cases.map(s => [s.tc_id, s]));

        const tcs: ModalTcRow[] = suite.test_cases
          .filter(tc => tc.is_active)
          .sort((a, b) => (a.execution_order ?? 999) - (b.execution_order ?? 999))
          .map((tc, idx) => {
            const scriptInfo = scriptMap.get(tc.id);
            return {
              id: tc.id,
              tc_code: tc.tc_code,
              title: tc.title,
              execution_order: tc.execution_order ?? (idx + 1),
              excluded: tc.excluded_from_run,
              has_script: scriptInfo?.has_script ?? false,
              placeholder_count: scriptInfo?.placeholder_count ?? 0,
              source: scriptInfo?.source,
            };
          });

        this.runModalTcs.set(tcs);
        this.isLoadingModalTcs.set(false);
        this.runModalStep.set(2);
      },
      error: () => {
        this.isLoadingModalTcs.set(false);
        this.toastService.error('Failed to load suite test cases');
      },
    });
  }

  backToStep1(): void { this.runModalStep.set(1); }

  dropTcInModal(event: CdkDragDrop<ModalTcRow[]>): void {
    const list = [...this.runModalTcs()];
    moveItemInArray(list, event.previousIndex, event.currentIndex);
    this.runModalTcs.set(list);
  }

  toggleTcExcluded(tc: ModalTcRow): void {
    this.runModalTcs.update(list =>
      list.map(t => t.id === tc.id ? { ...t, excluded: !t.excluded } : t)
    );
  }

  startSuiteRun(): void {
    if (this.modalErrors().length > 0) return;

    const suiteId = this.runModalSuiteId();
    const suiteName = this.runModalSuiteName();

    // Save execution order + excluded state for each TC
    this.isSavingOrder.set(true);
    const updates = this.runModalTcs().map((tc, idx) =>
      this.testSuiteService.updateTcExecution(tc.id, {
        execution_order: idx + 1,
        excluded_from_run: tc.excluded,
      }).pipe(catchError(() => of(null)))
    );

    forkJoin(updates).subscribe({
      next: () => {
        this.isSavingOrder.set(false);
        this.showRunModal.set(false);
        this.suiteRunningName.set(suiteName);
        this.isSuiteRunning.set(true);
        this.showSuitePanel.set(true);
        this.suiteLogEntries.set([]);
        this.suiteRunSummary.set(null);

        this.suiteSub?.unsubscribe();
        this.suiteSub = this.playwrightService.connectSuiteStream(suiteId).subscribe({
          next: (event) => this._handleSuiteEvent(event),
          error: () => {
            this.isSuiteRunning.set(false);
            this.toastService.error('Execution stream disconnected');
          },
          complete: () => this.isSuiteRunning.set(false),
        });

        this.playwrightService.executeSuiteSmart(suiteId, {
          app_url: this.runModalAppUrl(),
          browser: this.runModalBrowser(),
          headless: this.runModalHeadless(),
          stop_on_failure: this.runModalStopOnFail(),
          model_id: this.runModalModel(),
        }).subscribe({
          error: () => {
            this.isSuiteRunning.set(false);
            this.toastService.error('Failed to start suite execution');
          },
        });
      },
      error: () => {
        this.isSavingOrder.set(false);
        this.toastService.error('Failed to save execution order');
      },
    });
  }

  private _handleSuiteEvent(event: SuiteSSEEvent): void {
    const tcs = this.runModalTcs();
    switch (event.type) {
      case 'suite_started': {
        const tcIds: string[] = event.data['test_case_ids'] || [];
        this.suiteLogEntries.set(tcIds.map(id => {
          const tc = tcs.find(t => t.id === id);
          return { tc_id: id, tc_code: tc?.tc_code ?? '?', title: tc?.title ?? id, status: 'pending' };
        }));
        break;
      }
      case 'tc_started': {
        const id = event.data['tc_id'];
        this.suiteLogEntries.update(entries =>
          entries.map(e => e.tc_id === id ? { ...e, status: 'running' } : e)
        );
        break;
      }
      case 'tc_completed': {
        const id     = event.data['tc_id'];
        const status = (event.data['status'] ?? 'failed') as SuiteLogEntry['status'];
        const runId  = event.data['run_id'];
        this.suiteLogEntries.update(entries =>
          entries.map(e => e.tc_id === id ? { ...e, status, run_id: runId } : e)
        );
        if (status === 'passed') {
          this.toastService.success(`${event.data['tc_code'] ?? id} — passed`);
        } else if (status === 'failed') {
          this.toastService.error(`${event.data['tc_code'] ?? id} — failed`);
        }
        break;
      }
      case 'completed': {
        this.isSuiteRunning.set(false);
        this.suiteRunSummary.set({
          total:    event.data['total']    ?? 0,
          passed:   event.data['passed']   ?? 0,
          failed:   event.data['failed']   ?? 0,
          skipped:  event.data['skipped']  ?? 0,
          duration: event.data['duration'] ?? 0,
        });
        this.loadData();
        break;
      }
    }
  }

  closeSuitePanel(): void {
    this.showSuitePanel.set(false);
    this.suiteLogEntries.set([]);
    this.suiteRunSummary.set(null);
  }

  downloadReport(): void {
    const entries = this.suiteLogEntries();
    const summary = this.suiteRunSummary();
    const suiteId = this.runModalSuiteId();
    const suiteName = this.suiteRunningName();

    if (!suiteId || !entries.some(e => !!e.run_id)) {
      this.toastService.error('No run data available to export');
      return;
    }

    this.isDownloadingReport.set(true);
    const safeTitle = suiteName.replace(/[^a-z0-9]+/gi, '-').toLowerCase();
    const dateStr   = new Date().toISOString().slice(0, 10);

    this.testSuiteService.exportSuiteReport(suiteId, {
      suite_name: suiteName,
      summary: summary ?? null,
      entries: entries.map(e => ({ run_id: e.run_id, tc_code: e.tc_code, title: e.title, status: e.status })),
    }).subscribe({
      next: (blob) => {
        this.testSuiteService.downloadBlob(blob, `report-${safeTitle}-${dateStr}.pdf`);
        this.isDownloadingReport.set(false);
      },
      error: () => {
        this.toastService.error('Failed to generate PDF report');
        this.isDownloadingReport.set(false);
      },
    });
  }

  // ── Email dialog for a single failed TC run ───────────────────────────────────
  openEmailDialog(): void {
    this.emailTo.set('');
    this.showEmailDialog.set(true);
  }

  closeEmailDialog(): void { this.showEmailDialog.set(false); }

  sendFailedReports(): void {
    const failedEntries = this.suiteLogEntries().filter(e => e.status === 'failed' && e.run_id);
    if (failedEntries.length === 0) { this.toastService.error('No failed test runs to report'); return; }

    const raw = this.emailTo().trim();
    const recipients = raw.split(/[,;\n]+/).map(r => r.trim()).filter(r => r.includes('@'));
    if (!recipients.length) { this.toastService.error('Enter at least one valid email'); return; }

    this.isSendingEmail.set(true);
    const sends = failedEntries.map(e =>
      this.playwrightService.sendReportEmail(e.run_id!, recipients).pipe(catchError(() => of(null)))
    );

    forkJoin(sends).subscribe({
      next: () => {
        this.isSendingEmail.set(false);
        this.showEmailDialog.set(false);
        this.toastService.success(`Failed TC reports sent to ${recipients.join(', ')}`);
      },
      error: () => {
        this.isSendingEmail.set(false);
        this.toastService.error('Failed to send emails');
      },
    });
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

  getEntryStatusClass(status: SuiteLogEntry['status']): string {
    switch (status) {
      case 'passed':  return 'entry-passed';
      case 'failed':  return 'entry-failed';
      case 'running': return 'entry-running';
      case 'skipped': return 'entry-skipped';
      default: return 'entry-pending';
    }
  }

  getEntryStatusIcon(status: SuiteLogEntry['status']): string {
    switch (status) {
      case 'passed':  return '✓';
      case 'failed':  return '✗';
      case 'running': return '▶';
      case 'skipped': return '⊘';
      default: return '○';
    }
  }

  formatDuration(seconds: number): string {
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }

  getScriptBadgeLabel(tc: ModalTcRow): string {
    if (!tc.has_script) return 'No script — auto-generate';
    if (tc.source === 'v2_corrected') return 'v2 Corrected';
    if (tc.placeholder_count > 0) return `v1 Draft · ${tc.placeholder_count} placeholder${tc.placeholder_count !== 1 ? 's' : ''}`;
    return 'v1 Draft';
  }

  getScriptBadgeClass(tc: ModalTcRow): string {
    if (!tc.has_script) return 'badge-autogen';
    if (tc.source === 'v2_corrected') return 'badge-v2';
    if (tc.placeholder_count > 0) return 'badge-v1-ph';
    return 'badge-v1';
  }

  includedTcCount(): number {
    return this.runModalTcs().filter(t => !t.excluded).length;
  }

  noScriptCount(): number {
    return this.runModalTcs().filter(t => !t.excluded && !t.has_script).length;
  }
}
