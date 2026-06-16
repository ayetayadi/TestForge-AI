import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Subscription, forkJoin, of } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { DragDropModule, CdkDragDrop, moveItemInArray } from '@angular/cdk/drag-drop';

import {
  PlaywrightE2EService, SuiteSSEEvent, SuiteScriptStatus, AvailableModel,
} from '../../services/playwright-e2e.service';
import { TestSuiteService } from '../../services/test-suite.service';
import { ToastService } from '../../services/toast.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { TestSuiteListItem } from '../../models/test-suite.model';
import {
  TestExecutionBasic, TestExecutionGlobalStats,
} from '../../models/playwright.models';

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

interface SuiteLogEntry {
  tc_id: string;
  tc_code: string;
  title: string;
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped' | 'error';
  tc_result_id?: string;
}

@Component({
  selector: 'app-test-execution',
  standalone: true,
  imports: [
    CommonModule, FormsModule, DragDropModule, SpinnerComponent,
  ],
  templateUrl: './test-execution.component.html',
  styleUrls: ['./test-execution.component.scss'],
})
export class TestExecutionComponent implements OnInit, OnDestroy {
  private playwrightService = inject(PlaywrightE2EService);
  private testSuiteService  = inject(TestSuiteService);
  private toastService      = inject(ToastService);
  private router            = inject(Router);

  // ── Page state ────────────────────────────────────────────────────────────────
  isLoading      = signal(true);
  executions     = signal<TestExecutionBasic[]>([]);
  globalStats    = signal<TestExecutionGlobalStats | null>(null);
  suites         = signal<TestSuiteListItem[]>([]);

  // ── Pagination ────────────────────────────────────────────────────────────────
  readonly pageSize = 10;
  currentPage = signal(1);
  pagedExecutions = computed(() => {
    const start = (this.currentPage() - 1) * this.pageSize;
    return this.executions().slice(start, start + this.pageSize);
  });
  totalPages = computed(() => Math.max(1, Math.ceil(this.executions().length / this.pageSize)));
  pageNumbers = computed(() => Array.from({ length: this.totalPages() }, (_, i) => i + 1));

  // ── Delete ───────────────────────────────────────────────────────────────────
  deletingId = signal<string | null>(null);

  // ── Relaunch ─────────────────────────────────────────────────────────────────
  relaunchingId = signal<string | null>(null);

  // ── Run modal ────────────────────────────────────────────────────────────────
  showRunModal       = signal(false);
  runModalStep       = signal<1 | 2>(1);
  runModalSuiteId    = signal<string>('');
  runModalAppUrl     = signal('');
  runModalBrowser    = signal<'chromium' | 'firefox' | 'webkit'>('chromium');
  runModalHeadless   = signal(true);
  runModalStopOnFail = signal(false);
  runModalModel      = signal('openai/gpt-oss-120b');
  runModalTcs        = signal<ModalTcRow[]>([]);
  isLoadingModalTcs  = signal(false);
  isSavingOrder      = signal(false);
  availableModels    = signal<AvailableModel[]>([]);

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

  // ── Live panel (running execution) ───────────────────────────────────────────
  isSuiteRunning   = signal(false);
  showLivePanel    = signal(false);
  suiteLogEntries  = signal<SuiteLogEntry[]>([]);
  suiteRunningName = signal('');
  currentExecutionId = signal<string | null>(null);

  private suiteSub: Subscription | null = null;

  readonly browsers: ('chromium' | 'firefox' | 'webkit')[] = ['chromium', 'firefox', 'webkit'];

  // ── Computed ─────────────────────────────────────────────────────────────────
  includedTcCount = computed(() => this.runModalTcs().filter(t => !t.excluded).length);
  noScriptCount   = computed(() => this.runModalTcs().filter(t => !t.excluded && !t.has_script).length);

  // ── Lifecycle ────────────────────────────────────────────────────────────────
  ngOnInit(): void {
    this.loadExecutions();
    this.loadSuites();
    this.loadAvailableModels();
  }

  ngOnDestroy(): void {
    this.suiteSub?.unsubscribe();
  }

  // ── Data loading ─────────────────────────────────────────────────────────────
  loadExecutions(): void {
    this.isLoading.set(true);
    this.currentPage.set(1);
    this.playwrightService.listTestExecutions({ limit: 200 }).subscribe({
      next: (res) => {
        this.executions.set(res.items);
        this.globalStats.set(res.stats);
        this.isLoading.set(false);
      },
      error: () => {
        this.toastService.error('Failed to load executions');
        this.isLoading.set(false);
      },
    });
  }

  goToPage(page: number): void {
    if (page < 1 || page > this.totalPages()) return;
    this.currentPage.set(page);
  }

  deleteExecution(ex: TestExecutionBasic, event: Event): void {
    event.stopPropagation();
    if (!confirm(`Delete execution of "${ex.suite_title || 'this suite'}"? This cannot be undone.`)) return;
    this.deletingId.set(ex.id);
    this.playwrightService.deleteExecution(ex.id).subscribe({
      next: () => {
        this.executions.update(list => list.filter(e => e.id !== ex.id));
        this.toastService.success('Execution deleted');
        if (this.currentPage() > this.totalPages()) this.currentPage.set(this.totalPages());
        this.deletingId.set(null);
      },
      error: () => {
        this.toastService.error('Failed to delete execution');
        this.deletingId.set(null);
      },
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

  // ── Run modal ────────────────────────────────────────────────────────────────
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

  closeRunModal(): void { this.showRunModal.set(false); this.runModalStep.set(1); }

  proceedToStep2(): void {
    const suiteId = this.runModalSuiteId();
    if (!suiteId) { this.toastService.error('Please select a test suite'); return; }
    if (!this.runModalAppUrl().trim()) { this.toastService.error('App URL is required'); return; }

    this.isLoadingModalTcs.set(true);

    forkJoin({
      suite:   this.testSuiteService.getById(suiteId),
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
        this._launchSuite(suiteId, suiteName, {
          app_url: this.runModalAppUrl(),
          browser: this.runModalBrowser(),
          headless: this.runModalHeadless(),
          stop_on_failure: this.runModalStopOnFail(),
          model_id: this.runModalModel(),
        });
      },
      error: () => {
        this.isSavingOrder.set(false);
        this.toastService.error('Failed to save execution order');
      },
    });
  }

  /**
   * Relance une exécution avec la même configuration (suite, URL, navigateur).
   * Recharge les TCs de la suite pour afficher leurs codes/titres dans le panneau live.
   */
  relaunchExecution(ex: TestExecutionBasic, event: Event): void {
    event.stopPropagation();
    if (this.isSuiteRunning()) {
      this.toastService.error('A suite is already running — wait for it to finish');
      return;
    }

    const suiteId = ex.suite_id;
    const suiteName = ex.suite_title || 'Test suite';
    this.relaunchingId.set(ex.id);

    this.testSuiteService.getById(suiteId).subscribe({
      next: (suite) => {
        const tcs: ModalTcRow[] = suite.test_cases
          .filter(tc => tc.is_active)
          .sort((a, b) => (a.execution_order ?? 999) - (b.execution_order ?? 999))
          .map((tc, idx) => ({
            id: tc.id,
            tc_code: tc.tc_code,
            title: tc.title,
            execution_order: tc.execution_order ?? (idx + 1),
            excluded: tc.excluded_from_run,
            has_script: false,
            placeholder_count: 0,
          }));
        this.runModalTcs.set(tcs);
        this.relaunchingId.set(null);
        this._launchSuite(suiteId, suiteName, {
          app_url: ex.app_url,
          browser: ex.browser as 'chromium' | 'firefox' | 'webkit',
          headless: ex.headless,
          stop_on_failure: false,
          model_id: this.runModalModel(),
        });
      },
      error: () => {
        this.relaunchingId.set(null);
        this.toastService.error('Failed to load suite for relaunch');
      },
    });
  }

  /** Shared launch path: opens the live panel, the SSE stream, and fires the run. */
  private _launchSuite(
    suiteId: string,
    suiteName: string,
    opts: {
      app_url: string;
      browser: 'chromium' | 'firefox' | 'webkit';
      headless: boolean;
      stop_on_failure: boolean;
      model_id: string;
    },
  ): void {
    this.suiteRunningName.set(suiteName);
    this.isSuiteRunning.set(true);
    this.showLivePanel.set(true);
    this.suiteLogEntries.set([]);
    this.currentExecutionId.set(null);

    this.suiteSub?.unsubscribe();
    this.suiteSub = this.playwrightService.connectSuiteStream(suiteId).subscribe({
      next: (event) => this._handleSuiteEvent(event),
      error: () => {
        this.isSuiteRunning.set(false);
        this.toastService.error('Execution stream disconnected');
      },
      complete: () => this.isSuiteRunning.set(false),
    });

    this.playwrightService.executeSuiteSmart(suiteId, opts).subscribe({
      error: () => {
        this.isSuiteRunning.set(false);
        this.toastService.error('Failed to start suite execution');
      },
    });
  }

  private _handleSuiteEvent(event: SuiteSSEEvent): void {
    const tcs = this.runModalTcs();
    switch (event.type) {
      case 'suite_started': {
        const tcIds: string[] = event.data['test_case_ids'] || [];
        this.currentExecutionId.set(event.data['execution_id'] || null);
        this.suiteLogEntries.set(tcIds.map(id => {
          const tc = tcs.find(t => t.id === id);
          return {
            tc_id: id, tc_code: tc?.tc_code ?? '?',
            title: tc?.title ?? id, status: 'pending',
          };
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
        const tcResId  = event.data['tc_result_id'];
        this.suiteLogEntries.update(entries =>
          entries.map(e => e.tc_id === id ? { ...e, status, tc_result_id: tcResId } : e)
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
        this.loadExecutions();
        break;
      }
    }
  }

  closeLivePanel(): void {
    this.showLivePanel.set(false);
    this.suiteLogEntries.set([]);
  }

  getScriptBadgeLabel(tc: ModalTcRow): string {
    if (!tc.has_script) return 'No script — auto-generate';
    if (tc.source === 'v2_corrected') return 'v2 Corrected';
    if (tc.placeholder_count > 0) return `v1 Draft · ${tc.placeholder_count} ph`;
    return 'v1 Draft';
  }

  getScriptBadgeClass(tc: ModalTcRow): string {
    if (!tc.has_script) return 'badge-autogen';
    if (tc.source === 'v2_corrected') return 'badge-v2';
    if (tc.placeholder_count > 0) return 'badge-v1-ph';
    return 'badge-v1';
  }

  // ── Detail navigation ────────────────────────────────────────────────────────
  openDetail(executionId: string): void {
    this.router.navigate(['/test-execution', executionId]);
  }

  // ── UI helpers ────────────────────────────────────────────────────────────────
  getStatusClass(status: string): string {
    switch (status) {
      case 'passed':    return 'status--passed';
      case 'failed':    return 'status--failed';
      case 'error':     return 'status--error';
      case 'skipped':   return 'status--skipped';
      case 'running':   return 'status--running';
      case 'completed': return 'status--passed';
      case 'aborted':   return 'status--error';
      default:          return 'status--pending';
    }
  }

  getStatusIcon(status: string): string {
    switch (status) {
      case 'passed':  return '✓';
      case 'failed':  return '✗';
      case 'error':   return '⚠';
      case 'skipped': return '⊘';
      case 'running': return '▶';
      default:        return '○';
    }
  }

  formatDuration(seconds: number | null | undefined): string {
    if (!seconds || seconds <= 0) return '—';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }

  formatDate(iso: string | null | undefined): string {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleString();
  }
}
