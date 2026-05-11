import { Component, OnInit, OnDestroy, inject, signal, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { firstValueFrom, forkJoin, Subscription } from 'rxjs';

import { PlaywrightE2EService, SuiteSmartRunRequest, SuiteSSEEvent, SuiteScriptStatus } from '../../services/playwright-e2e.service';

import { TestSuiteService } from '../../services/test-suite.service';
import { ToastService } from '../../services/toast.service';

import {
  TestSuiteDetail,
  EmbeddedTestCase,
  DependencyNode,
  DependencyEdge,
  SUITE_TYPE_CONFIG,
  SUITE_STATUS_CONFIG,
  PRIORITY_CONFIG,
  MITIGATION_STATUS_CONFIG,
  RiskCoverage,
  UsAcCoverage,
} from '../../models/test-suite.model';

type DetailTab = 'overview' | 'cases' | 'traceability' | 'graph';

// ── Graph layout interfaces ──────────────────────────────────────────────────

interface GraphNodeLayout {
  id: string;
  tc_code: string;
  title: string;
  priority: string | null;
  test_type: string | null;
  x: number;
  y: number;
  exec_pos: number;
}

interface GraphEdgeLayout {
  path: string;
  label_x: number;
  label_y: number;
  source_code: string;
  target_code: string;
  dependency_type: string;
  color: string;
}

interface LayerBand {
  y: number;
  height: number;
  label: string;
  count: number;
  fill: string;
  text_color: string;
}

interface GraphLayoutData {
  nodes: GraphNodeLayout[];
  edges: GraphEdgeLayout[];
  svg_width: number;
  svg_height: number;
  bands: LayerBand[];
}

interface SuiteLogEntry {
  tc_id: string;
  tc_code: string;
  title: string;
  status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped';
  run_id?: string;
}

@Component({
  selector: 'app-test-suite-detail',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './test-suite-detail.component.html',
  styleUrl: './test-suite-detail.component.scss',
})
export class TestSuiteDetailComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(TestSuiteService);
  private toast = inject(ToastService);
  private playwrightService = inject(PlaywrightE2EService);

  // ── State ─────────────────────────────────────────────────────
  suite = signal<TestSuiteDetail | null>(null);
  isLoading = signal(true);
  activeTab = signal<DetailTab>('overview');
  expandedCase = signal<string | null>(null);

  // ── Suite Playwright Run ─────────────────────────────────────
  showSuiteRunModal   = signal(false);
  suiteModalStep      = signal<1 | 2>(1);
  suiteRunAppUrl      = signal('');
  suiteRunBrowser     = signal('chromium');
  suiteRunHeadless    = signal(true);
  suiteRunStopOnFail  = signal(false);
  isSuiteRunning      = signal(false);
  showSuitePanel      = signal(false);
  suiteLogEntries     = signal<SuiteLogEntry[]>([]);
  suiteRunSummary     = signal<{ total: number; passed: number; failed: number; skipped: number; duration: number } | null>(null);
  suiteScriptStatuses = signal<SuiteScriptStatus[]>([]);
  isLoadingStatuses   = signal(false);

  isDownloadingReport = signal(false);

  private _suiteSub: Subscription | null = null;

  // ── Status / Delete actions ───────────────────────────────────
  isActivating = signal(false);
  isArchiving = signal(false);
  isDeletingSuite = signal(false);
  showDeleteConfirm = signal(false);

  // ── Test Cases — Filters & Pagination ────────────────────────
  tcSearch = signal('');
  tcPriorityFilter = signal<string>('all');
  tcTypeFilter = signal<string>('all');
  tcShowInactive = signal(false);
  tcPage = signal(0);
  readonly TC_PAGE_SIZE = 8;

  // ── Overview — Section toggles ────────────────────────────────
  lifecycleOpen = signal(true);
  execStrategyOpen = signal(false);
  execOrderOpen = signal(true);

  // ── Coverage — Card body toggles ─────────────────────────────
  riskCoverageOpen = signal(true);
  acCoverageOpen = signal(true);

  // ── Traceability — Filter ─────────────────────────────────────
  tmCoverageFilter = signal<'all' | 'covered' | 'partial' | 'none'>('all');

  // ── Graph zoom / pan ──────────────────────────────────────────
  @ViewChild('graphCanvas') private _graphCanvas!: ElementRef<HTMLDivElement>;
  @ViewChild('graphSvg')    private _graphSvg!: ElementRef<SVGElement>;

  graphScale     = signal(1);
  graphTranslateX = signal(0);
  graphTranslateY = signal(0);
  isDragging     = signal(false);

  private _dragStartX  = 0;
  private _dragStartY  = 0;
  private _dragStartTX = 0;
  private _dragStartTY = 0;

  // ── Constants ─────────────────────────────────────────────────
  readonly SUITE_TYPE_CONFIG = SUITE_TYPE_CONFIG;
  readonly SUITE_STATUS_CONFIG = SUITE_STATUS_CONFIG;
  readonly PRIORITY_CONFIG = PRIORITY_CONFIG;
  readonly MITIGATION_STATUS_CONFIG = MITIGATION_STATUS_CONFIG;  // 🆕

  readonly tabs: { id: DetailTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'cases', label: 'Test Cases' },
    { id: 'traceability', label: 'Traceability Matrix' },
    { id: 'graph', label: 'Dependency Graph' },
  ];

  // ── Computed ──────────────────────────────────────────────────
  get suiteData(): TestSuiteDetail | null {
    return this.suite();
  }

  // ── Lifecycle ─────────────────────────────────────────────────
  async ngOnInit() {
    const id = this.route.snapshot.paramMap.get('suiteId');
    if (!id) {
      this.router.navigate(['/test-suites']);
      return;
    }

    await this.loadSuite(id);
  }

  async loadSuite(id: string) {
    this.isLoading.set(true);
    try {
      const detail = await firstValueFrom(this.service.getById(id));
      this.suite.set(detail ?? null);
      if (detail) {
        this._restoreLastRun(id);
      }
    } catch (err) {
      console.error('Failed to load test suite:', err);
      this.toast.error('Failed to load test suite');
    } finally {
      this.isLoading.set(false);
    }
  }

  private _restoreLastRun(suiteId: string): void {
    this.playwrightService.getLastSuiteRun(suiteId).subscribe({
      next: (data) => {
        if (!data.has_runs || !data.results.length) return;
        // Don't overwrite a live/in-progress run
        if (this.isSuiteRunning()) return;
        this.suiteLogEntries.set(
          data.results.map(r => ({
            tc_id: r.tc_id,
            tc_code: r.tc_code,
            title: r.title,
            status: r.status as SuiteLogEntry['status'],
            run_id: r.run_id ?? undefined,
          }))
        );
        if (data.summary) {
          this.suiteRunSummary.set(data.summary);
          this.showSuitePanel.set(true);
        }
      },
      error: () => { /* silent — panel just stays empty */ },
    });
  }

  // ── Status / Delete actions ───────────────────────────────────
  async activateSuite() {
    const id = this.suite()?.id;
    if (!id) return;
    this.isActivating.set(true);
    try {
      const updated = await firstValueFrom(this.service.update(id, { status: 'active' }));
      this.suite.set(updated);
      this.toast.success('Suite activated');
    } catch {
      this.toast.error('Failed to activate suite');
    } finally {
      this.isActivating.set(false);
    }
  }

  async archiveSuite() {
    const id = this.suite()?.id;
    if (!id) return;
    this.isArchiving.set(true);
    try {
      const updated = await firstValueFrom(this.service.update(id, { status: 'archived' }));
      this.suite.set(updated);
      this.toast.success('Suite archived');
    } catch {
      this.toast.error('Failed to archive suite');
    } finally {
      this.isArchiving.set(false);
    }
  }

  async deleteSuite() {
    const id = this.suite()?.id;
    if (!id) return;
    this.isDeletingSuite.set(true);
    try {
      await firstValueFrom(this.service.delete(id));
      this.toast.success('Suite deleted');
      this.router.navigate(['/test-suites']);
    } catch {
      this.toast.error('Failed to delete suite');
      this.isDeletingSuite.set(false);
    }
  }

  ngOnDestroy(): void {
    this._suiteSub?.unsubscribe();
  }

  // ── Suite Playwright Run ──────────────────────────────────────
  openSuiteRunModal(): void {
    this.suiteModalStep.set(1);
    this.suiteScriptStatuses.set([]);
    this.showSuiteRunModal.set(true);
  }
  closeSuiteRunModal(): void {
    this.showSuiteRunModal.set(false);
    this.suiteModalStep.set(1);
  }
  backToStep1(): void            { this.suiteModalStep.set(1); }
  toggleSuiteHeadless(): void    { this.suiteRunHeadless.set(!this.suiteRunHeadless()); }
  toggleSuiteStopOnFail(): void  { this.suiteRunStopOnFail.set(!this.suiteRunStopOnFail()); }

  loadAndReview(): void {
    const suiteId = this.suite()?.id;
    if (!suiteId || !this.suiteRunAppUrl()) return;
    this.isLoadingStatuses.set(true);
    this.playwrightService.getSuiteScriptsStatus(suiteId).subscribe({
      next: (res) => {
        this.suiteScriptStatuses.set(res.test_cases);
        this.suiteModalStep.set(2);
        this.isLoadingStatuses.set(false);
      },
      error: () => {
        this.toast.error('Failed to load script statuses');
        this.isLoadingStatuses.set(false);
      },
    });
  }

  getScriptReadyCount(): number {
    return this.suiteScriptStatuses().filter(s => s.has_script).length;
  }

  getScriptPendingCount(): number {
    return this.suiteScriptStatuses().filter(s => !s.has_script).length;
  }

  startSuiteRun(): void {
    const suiteId = this.suite()?.id;
    if (!suiteId || !this.suiteRunAppUrl()) return;

    this.showSuiteRunModal.set(false);
    this.isSuiteRunning.set(true);
    this.showSuitePanel.set(true);
    this.suiteLogEntries.set([]);
    this.suiteRunSummary.set(null);

    this._suiteSub?.unsubscribe();
    this._suiteSub = this.playwrightService.connectSuiteStream(suiteId).subscribe({
      next: (event) => this._handleSuiteEvent(event),
      error: (err) => {
        console.error('[SUITE SSE] Error:', err);
        this.isSuiteRunning.set(false);
        this.toast.error('Execution stream disconnected');
      },
      complete: () => this.isSuiteRunning.set(false),
    });

    this.playwrightService.executeSuiteSmart(suiteId, {
      app_url:          this.suiteRunAppUrl(),
      browser:          this.suiteRunBrowser(),
      headless:         this.suiteRunHeadless(),
      stop_on_failure:  this.suiteRunStopOnFail(),
    }).subscribe({
      error: (err) => {
        console.error('[SUITE RUN] Start error:', err);
        this.isSuiteRunning.set(false);
        this.toast.error('Failed to start suite execution');
      },
    });
  }

  downloadSuiteReport(): void {
    const entries = this.suiteLogEntries();
    const summary = this.suiteRunSummary();
    const suiteName = this.suite()?.title ?? 'suite';

    const runEntries = entries.filter(e => !!e.run_id);
    if (!runEntries.length) {
      this.toast.error('No run data available to export');
      return;
    }

    this.isDownloadingReport.set(true);

    forkJoin(runEntries.map(e => this.playwrightService.getTestRunDetails(e.run_id!))).subscribe({
      next: (details) => {
        const now = new Date();
        const lines: string[] = [
          '================================================================',
          'SUITE EXECUTION REPORT',
          '================================================================',
          `Suite   : ${suiteName}`,
          `Date    : ${now.toLocaleString()}`,
          summary
            ? `Results : ${summary.passed} passed | ${summary.failed} failed | ${summary.skipped} skipped | ${summary.duration.toFixed(1)}s total`
            : '',
          '',
        ];

        runEntries.forEach((entry, i) => {
          const detail = details[i];
          const statusIcon = entry.status === 'passed' ? '✓' : entry.status === 'failed' ? '✗' : '—';
          lines.push(`────────────────────────────────────────────────────────────`);
          lines.push(`[${statusIcon}] ${entry.tc_code} — ${entry.title}`);
          lines.push(`    Status   : ${entry.status.toUpperCase()}`);
          if (detail?.test_run) {
            lines.push(`    Browser  : ${detail.test_run.browser}`);
            lines.push(`    Duration : ${(detail.test_run.duration ?? 0).toFixed(1)}s`);
            lines.push(`    Run ID   : ${detail.test_run.id}`);
          }
          if (detail?.result?.justification) {
            lines.push(`    Result   : ${detail.result.justification}`);
          }
          if (detail?.steps?.length) {
            lines.push('');
            lines.push('    Steps:');
            detail.steps.forEach(s => {
              const icon = s.status === 'success' ? '  ✓' : '  ✗';
              const type = s.type.toUpperCase().padEnd(7);
              lines.push(`${icon} [${type}] ${s.content}`);
            });
          }
          lines.push('');
        });

        // Entries with no run_id (skipped before execution)
        entries.filter(e => !e.run_id).forEach(entry => {
          lines.push(`────────────────────────────────────────────────────────────`);
          lines.push(`[—] ${entry.tc_code} — ${entry.title}`);
          lines.push(`    Status: ${entry.status.toUpperCase()}`);
          lines.push('');
        });

        lines.push('================================================================');

        const blob = new Blob([lines.join('\n')], { type: 'text/plain;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const safeTitle = suiteName.replace(/[^a-z0-9]+/gi, '-').toLowerCase();
        const dateStr = now.toISOString().slice(0, 10);
        this._triggerDownload(url, `report-${safeTitle}-${dateStr}.txt`);
        this.isDownloadingReport.set(false);
      },
      error: () => {
        this.toast.error('Failed to generate report');
        this.isDownloadingReport.set(false);
      },
    });
  }

  private _handleSuiteEvent(event: SuiteSSEEvent): void {
    switch (event.type) {
      case 'suite_started': {
        const tcIds: string[] = event.data['test_case_ids'] || [];
        const tcs = this.getTestCases();
        this.suiteLogEntries.set(tcIds.map(id => {
          const tc = tcs.find(t => t.id === id);
          return { tc_id: id, tc_code: tc?.tc_code || '?', title: tc?.title || id, status: 'pending' };
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
        break;
      }
    }
  }

  suiteStatusLabel(status: SuiteLogEntry['status']): string {
    return status.charAt(0).toUpperCase() + status.slice(1);
  }

  // ── Navigation ────────────────────────────────────────────────
  goBack() {
    this.router.navigate(['/test-suites']);
  }

  goToTestPlan() {
    const planId = this.suite()?.test_plan?.id;
    if (planId) {
      this.router.navigate(['/test-plans', planId]);
    }
  }

  openTestCase(tcId: string) {
    this.router.navigate(['/test-cases', tcId]);
  }

  goToUserStory(usId: string) {
    this.router.navigate(['/user-stories', usId]);  // 🆕
  }

  // ── Section toggle helpers ────────────────────────────────────
  toggleLifecycle()       { this.lifecycleOpen.update(v => !v); }
  toggleExecStrategy()    { this.execStrategyOpen.update(v => !v); }
  toggleExecOrder()       { this.execOrderOpen.update(v => !v); }
  toggleRiskCoverage()    { this.riskCoverageOpen.update(v => !v); }
  toggleAcCoverage()      { this.acCoverageOpen.update(v => !v); }
  setTmFilter(f: 'all' | 'covered' | 'partial' | 'none') { this.tmCoverageFilter.set(f); }

  // ── TC Filter / Pagination helpers ───────────────────────────
  setTcSearch(v: string) { this.tcSearch.set(v); this.tcPage.set(0); }
  setTcPriority(v: string) { this.tcPriorityFilter.set(v); this.tcPage.set(0); }
  setTcType(v: string) { this.tcTypeFilter.set(v); this.tcPage.set(0); }
  toggleShowInactive() { this.tcShowInactive.update(v => !v); this.tcPage.set(0); }

  getFilteredTestCases(): EmbeddedTestCase[] {
    let cases = this.getTestCases();
    if (!this.tcShowInactive()) cases = cases.filter(tc => tc.is_active);
    const q = this.tcSearch().toLowerCase().trim();
    if (q) cases = cases.filter(tc =>
      (tc.title ?? '').toLowerCase().includes(q) ||
      (tc.tc_code ?? '').toLowerCase().includes(q)
    );
    const prio = this.tcPriorityFilter();
    if (prio !== 'all') cases = cases.filter(tc => tc.priority === prio);
    const type = this.tcTypeFilter();
    if (type !== 'all') cases = cases.filter(tc => tc.test_type === type);
    return cases;
  }

  getPaginatedTestCases(): EmbeddedTestCase[] {
    const filtered = this.getFilteredTestCases();
    const start = this.tcPage() * this.TC_PAGE_SIZE;
    return filtered.slice(start, start + this.TC_PAGE_SIZE);
  }

  getTcTotalPages(): number {
    return Math.max(1, Math.ceil(this.getFilteredTestCases().length / this.TC_PAGE_SIZE));
  }

  tcPrevPage() { if (this.tcPage() > 0) this.tcPage.update(p => p - 1); }
  tcNextPage() { if (this.tcPage() < this.getTcTotalPages() - 1) this.tcPage.update(p => p + 1); }
  tcGoToPage(p: number) { this.tcPage.set(p); }

  getPaginationPages(): number[] {
    const total = this.getTcTotalPages();
    const current = this.tcPage();
    if (total <= 7) return Array.from({ length: total }, (_, i) => i);
    const pages = new Set<number>();
    pages.add(0);
    pages.add(total - 1);
    for (let i = Math.max(0, current - 2); i <= Math.min(total - 1, current + 2); i++) pages.add(i);
    return Array.from(pages).sort((a, b) => a - b);
  }

  getAvailableTcTypes(): string[] {
    return [...new Set(this.getTestCases().map(tc => tc.test_type).filter((t): t is string => !!t))];
  }

  isEllipsisBefore(idx: number): boolean {
    const pages = this.getPaginationPages();
    return idx > 0 && pages[idx] - pages[idx - 1] > 1;
  }

  getTcStartIndex(): number { return this.tcPage() * this.TC_PAGE_SIZE + 1; }
  getTcEndIndex(): number {
    return Math.min((this.tcPage() + 1) * this.TC_PAGE_SIZE, this.getFilteredTestCases().length);
  }

  // ── Traceability filter ───────────────────────────────────────
  getFilteredMatrixRows() {
    const matrix = this.getMatrix();
    if (!matrix) return [];
    const f = this.tmCoverageFilter();
    if (f === 'all') return matrix.rows;
    if (f === 'covered') return matrix.rows.filter(r => r.coverage_pct >= 100);
    if (f === 'partial') return matrix.rows.filter(r => r.coverage_pct > 0 && r.coverage_pct < 100);
    return matrix.rows.filter(r => r.coverage_pct === 0);
  }

  // ── UI helpers ────────────────────────────────────────────────
  toggleCase(id: string) {
    this.expandedCase.set(this.expandedCase() === id ? null : id);
  }

  isCaseExpanded(id: string): boolean {
    return this.expandedCase() === id;
  }

  getSuiteTypeConfig(type?: string | null) {
    return type ? (SUITE_TYPE_CONFIG[type] ?? null) : null;
  }

  getStatusConfig(status: string) {
    return SUITE_STATUS_CONFIG[status] ?? { label: status, color: '#6b7280', bg: '#f3f4f6' };
  }

  getPriorityConfig(prio?: string | null) {
    return prio ? (PRIORITY_CONFIG[prio] ?? null) : null;
  }

  // ── 🆕 RISK COVERAGE HELPERS ──────────────────────────────────

  getRiskCoverage(): RiskCoverage | null {
    return this.suite()?.risk_coverage ?? null;
  }

  getRiskCoverageColor(pct: number): string {
    if (pct >= 100) return '#10b981';  // Vert - full
    if (pct >= 80) return '#f59e0b';   // Orange - partial
    return '#ef4444';                   // Rouge - low
  }

  getRiskCoverageLabel(pct: number): string {
    if (pct >= 100) return 'Fully Mitigated';
    if (pct >= 80) return 'Partially Mitigated';
    return 'Not Mitigated';
  }

  getMitigationConfig(status: string) {
    return MITIGATION_STATUS_CONFIG[status] ?? { label: status, color: '#6b7280', bg: '#f3f4f6' };
  }

  // ── 🆕 AC COVERAGE PER US HELPERS ─────────────────────────────

  getUsAcCoverages(): UsAcCoverage[] {
    return this.suite()?.us_ac_coverages ?? [];
  }

  getUsWithTests(): UsAcCoverage[] {
    return this.getUsAcCoverages().filter(us => us.has_tests);
  }

  getUsWithoutTests(): UsAcCoverage[] {
    return this.getUsAcCoverages().filter(us => !us.has_tests);
  }

  getTotalAcCovered(): number {
    return this.getUsAcCoverages().reduce((sum, us) => sum + us.covered_ac, 0);
  }

  getTotalAc(): number {
    return this.getUsAcCoverages().reduce((sum, us) => sum + us.total_ac, 0);
  }

  getAverageAcCoverage(): number {
    const usWithTests = this.getUsWithTests();
    if (usWithTests.length === 0) return 0;
    const total = usWithTests.reduce((sum, us) => sum + us.ac_coverage_pct, 0);
    return Math.round(total / usWithTests.length);
  }

  getAcCoverageColor(pct: number): string {
    if (pct >= 100) return '#10b981';
    if (pct >= 80) return '#f59e0b';
    if (pct > 0) return '#ef4444';
    return '#9ca3af';  // Gris pour 0%
  }

  getAcCoverageLabel(us: UsAcCoverage): string {
    if (!us.has_tests) return 'No tests';
    if (us.ac_coverage_pct >= 100) return 'Complete';
    if (us.ac_coverage_pct >= 80) return 'Partial';
    return 'Low';
  }

  // ── RISK LEVEL HELPERS ────────────────────────────────────────

  getRiskLevelColor(level?: string | null): string {
    const map: Record<string, string> = {
      critical: '#dc2626', high: '#ea580c', medium: '#ca8a04', low: '#16a34a'
    };
    return level ? (map[level] ?? '#6b7280') : '#6b7280';
  }

  getRiskLevelBg(level?: string | null): string {
    const map: Record<string, string> = {
      critical: '#fee2e2', high: '#ffedd5', medium: '#fef9c3', low: '#dcfce7'
    };
    return level ? (map[level] ?? '#f3f4f6') : '#f3f4f6';
  }

  getDependencyEdgeColor(type: string): string {
    const map: Record<string, string> = {
      requires: '#6366f1', blocks: '#ef4444', related: '#6b7280'
    };
    return map[type] ?? '#6b7280';
  }

  getDependencyEdgeLabel(type: string): string {
    const map: Record<string, string> = {
      requires: 'Requires', blocks: 'Blocks', related: 'Related'
    };
    return map[type] ?? type;
  }

  formatDate(d?: string | null): string {
    if (!d) return '—';
    try {
      return new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return '—';
    }
  }

  gherkinLines(source?: string | null): { type: string; text: string }[] {
    if (!source) return [];
    return source.split('\n').map(line => {
      const t = line.trim();
      if (t.startsWith('@'))              return { type: 'tag', text: line };
      if (t.startsWith('Feature:'))       return { type: 'feature', text: line };
      if (t.startsWith('Scenario'))       return { type: 'scenario', text: line };
      if (t.startsWith('Given'))          return { type: 'step', text: line };
      if (t.startsWith('When'))           return { type: 'step', text: line };
      if (t.startsWith('Then'))           return { type: 'step', text: line };
      if (t.startsWith('And'))            return { type: 'step', text: line };
      if (t.startsWith('But'))            return { type: 'step', text: line };
      if (t.startsWith('|'))              return { type: 'table', text: line };
      if (t.startsWith('#'))              return { type: 'comment', text: line };
      return { type: 'other', text: line };
    });
  }

  priorityKeys(byPriority: Record<string, number>): string[] {
    const order = ['critical', 'high', 'medium', 'low'];
    return order.filter(k => byPriority[k]);
  }

  typeKeys(byType: Record<string, number>): string[] {
    return Object.keys(byType);
  }

  testDataEntries(data: Record<string, unknown>): { key: string; value: string }[] {
    if (!data) return [];
    return Object.entries(data).map(([k, v]) => ({ key: k, value: String(v) }));
  }

  // ── Lifecycle helpers ─────────────────────────────────────────
  getLifecycle() {
    return this.suite()?.lifecycle ?? null;
  }

  getRisks() {
    return this.suite()?.risks ?? [];
  }

  getRiskCount(): number {
    return this.suite()?.risks?.length ?? 0;
  }

  getMatrix() {
    return this.suite()?.traceability_matrix ?? null;
  }

  getGraph() {
    return this.suite()?.dependency_graph ?? null;
  }

  getTestCases() {
    return this.suite()?.test_cases ?? [];
  }

  getActiveTestCases() {
    return this.getTestCases().filter(tc => tc.is_active);
  }

  getAllSuitesOrder() {
    return this.suite()?.all_suites_order ?? [];
  }

  // ── Execution Strategy (replaces Priority Reasoning) ─────────
  private readonly _FLOW_ORDER = [
    'authentication', 'dashboard', 'crud', 'search',
    'reporting', 'settings', 'notifications', 'other',
  ];
  private readonly _FLOW_LABELS: Record<string, string> = {
    authentication: 'Authentication', dashboard: 'Dashboard', crud: 'CRUD',
    search: 'Search & Filter', reporting: 'Reporting & Logs', settings: 'Settings',
    notifications: 'Notifications', other: 'Other',
  };
  private readonly _FLOW_BG: Record<string, string> = {
    authentication: '#eff6ff', dashboard: '#f5f3ff', crud: '#f0fdf4',
    search: '#fff7ed', reporting: '#fffbeb', settings: '#f8fafc',
    notifications: '#fdf4ff', other: '#f9fafb',
  };
  private readonly _FLOW_TEXT: Record<string, string> = {
    authentication: '#1d4ed8', dashboard: '#7c3aed', crud: '#15803d',
    search: '#c2410c', reporting: '#b45309', settings: '#475569',
    notifications: '#9333ea', other: '#6b7280',
  };
  private readonly _FLOW_KEYWORDS: Record<string, string[]> = {
    authentication: ['auth', 'login', 'logout', 'register', 'signup', 'password', 'credential', 'session', 'token', 'sso', '2fa'],
    dashboard:      ['dashboard', 'home', 'overview', 'landing', 'summary', 'welcome'],
    crud:           ['create', 'update', 'delete', 'edit', 'add', 'remove', 'save', 'crud', 'form', 'submit'],
    search:         ['search', 'filter', 'sort', 'query', 'find', 'browse'],
    reporting:      ['report', 'export', 'log', 'audit', 'history', 'analytics', 'metrics'],
    settings:       ['setting', 'config', 'preference', 'profile', 'account', 'permission', 'role'],
    notifications:  ['notification', 'alert', 'email', 'message', 'push', 'reminder'],
  };

  private _detectFlowForTc(tc: EmbeddedTestCase): string {
    const text = `${tc.title ?? ''} ${(tc.tags ?? []).join(' ')}`.toLowerCase();
    for (const [flow, kws] of Object.entries(this._FLOW_KEYWORDS)) {
      if (kws.some(kw => text.includes(kw))) return flow;
    }
    return 'other';
  }

  getBusinessFlowGroups(): { flow: string; label: string; count: number; by_risk: Record<string, number>; bg_color: string; text_color: string }[] {
    const tcs = this.getTestCases();
    const groupMap: Record<string, { count: number; by_risk: Record<string, number> }> = {};
    for (const tc of tcs) {
      const flow = this._detectFlowForTc(tc);
      if (!groupMap[flow]) groupMap[flow] = { count: 0, by_risk: {} };
      groupMap[flow].count++;
      const risk = tc.priority ?? 'low';
      groupMap[flow].by_risk[risk] = (groupMap[flow].by_risk[risk] ?? 0) + 1;
    }
    return this._FLOW_ORDER
      .filter(f => groupMap[f])
      .map(f => ({
        flow: f,
        label: this._FLOW_LABELS[f] ?? f,
        count: groupMap[f].count,
        by_risk: groupMap[f].by_risk,
        bg_color: this._FLOW_BG[f] ?? '#f9fafb',
        text_color: this._FLOW_TEXT[f] ?? '#6b7280',
      }));
  }

  // ── Tab change (reset graph zoom) ────────────────────────────
  onTabChange(id: DetailTab) {
    if (id === 'graph') { this.resetZoom(); }
    this.activeTab.set(id);
  }

  // ── Graph zoom / pan / export ─────────────────────────────────

  getZoomPercent(): number {
    return Math.round(this.graphScale() * 100);
  }

  getZoomFillPct(): number {
    // slider range 0.2 → 4, map to 0 → 100%
    return ((this.graphScale() - 0.2) / (4 - 0.2)) * 100;
  }

  getGraphTransform(): string {
    return `translate(${this.graphTranslateX()}px, ${this.graphTranslateY()}px) scale(${this.graphScale()})`;
  }

  zoomIn()  { this.graphScale.set(Math.min(4,   this.graphScale() * 1.25)); }
  zoomOut() { this.graphScale.set(Math.max(0.2, this.graphScale() / 1.25)); }

  resetZoom() {
    this.graphScale.set(1);
    this.graphTranslateX.set(0);
    this.graphTranslateY.set(0);
  }

  onGraphWheel(event: WheelEvent) {
    event.preventDefault();
    const canvas = this._graphCanvas?.nativeElement;
    if (!canvas) return;

    const rect    = canvas.getBoundingClientRect();
    const mx      = event.clientX - rect.left;
    const my      = event.clientY - rect.top;
    const factor  = event.deltaY > 0 ? 0.9 : 1.1;
    const oldS    = this.graphScale();
    const newS    = Math.min(4, Math.max(0.2, oldS * factor));
    const ratio   = newS / oldS;

    this.graphScale.set(newS);
    this.graphTranslateX.set(mx - ratio * (mx - this.graphTranslateX()));
    this.graphTranslateY.set(my - ratio * (my - this.graphTranslateY()));
  }

  onGraphMouseDown(event: MouseEvent) {
    if (event.button !== 0) return;
    this.isDragging.set(true);
    this._dragStartX  = event.clientX;
    this._dragStartY  = event.clientY;
    this._dragStartTX = this.graphTranslateX();
    this._dragStartTY = this.graphTranslateY();
    event.preventDefault();
  }

  onGraphMouseMove(event: MouseEvent) {
    if (!this.isDragging()) return;
    this.graphTranslateX.set(this._dragStartTX + (event.clientX - this._dragStartX));
    this.graphTranslateY.set(this._dragStartTY + (event.clientY - this._dragStartY));
  }

  onGraphMouseUp() { this.isDragging.set(false); }

  exportGraphSvg() {
    const svgEl = this._graphSvg?.nativeElement;
    if (!svgEl) return;
    const blob = new Blob([new XMLSerializer().serializeToString(svgEl)], { type: 'image/svg+xml;charset=utf-8' });
    this._triggerDownload(URL.createObjectURL(blob), `dep-graph-${this.suite()?.title ?? 'suite'}.svg`);
  }

  exportGraphPng() {
    const svgEl = this._graphSvg?.nativeElement;
    if (!svgEl) return;
    const layout = this.buildGraphLayout();
    const w = (layout?.svg_width  ?? 800) * 2;
    const h = (layout?.svg_height ?? 600) * 2;

    const svgUrl = URL.createObjectURL(
      new Blob([new XMLSerializer().serializeToString(svgEl)], { type: 'image/svg+xml;charset=utf-8' })
    );
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement('canvas');
      canvas.width  = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d')!;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, w, h);
      ctx.drawImage(img, 0, 0, w, h);
      URL.revokeObjectURL(svgUrl);
      this._triggerDownload(canvas.toDataURL('image/png'), `dep-graph-${this.suite()?.title ?? 'suite'}.png`);
    };
    img.src = svgUrl;
  }

  private _triggerDownload(url: string, filename: string) {
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    if (url.startsWith('blob:')) setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ── Graph helpers ─────────────────────────────────────────────
  findNode(nodes: DependencyNode[], id: string): DependencyNode | undefined {
    return nodes.find(n => n.id === id);
  }

  hasEdge(edges: DependencyEdge[], nodeId: string): boolean {
    return edges.some(e => e.source_id === nodeId || e.target_id === nodeId);
  }

  getNodeEdges(edges: DependencyEdge[], nodeId: string): DependencyEdge[] {
    return edges.filter(e => e.source_id === nodeId || e.target_id === nodeId);
  }

  getExecutionPosition(code: string): number {
    const order = this.suite()?.dependency_graph?.execution_order ?? [];
    return order.indexOf(code) + 1;
  }

  // ── Traceability helpers ──────────────────────────────────────

  getCoveredStoriesCount(): number {
    const matrix = this.getMatrix();
    if (!matrix) return 0;
    return matrix.rows.filter(r => r.covered_cases > 0).length;
  }

  getUncoveredStoriesCount(): number {
    const matrix = this.getMatrix();
    if (!matrix) return 0;
    return matrix.rows.filter(r => r.covered_cases === 0).length;
  }

  /** Returns active test cases to use as matrix columns */
  getMatrixTestCaseHeaders(): EmbeddedTestCase[] {
    return this.getTestCases().filter(tc => tc.is_active);
  }

  /** True if tc_code appears in the covered_by array of an AC row */
  isAcCoveredByTc(coveredBy: string[], tcCode: string): boolean {
    return coveredBy.includes(tcCode);
  }

  /** Number of risks associated with a test case */
  getTcRiskCount(tc: EmbeddedTestCase): number {
    return tc.risk_ids?.length ?? 0;
  }
// test-suite-detail.component.ts

buildGraphLayout(): GraphLayoutData | null {
  const graph = this.getGraph();
  if (!graph || graph.nodes.length === 0) return null;

  const NODE_W  = 160;
  const NODE_H  = 60;
  const H_GAP   = 36;
  const V_GAP   = 80;
  const PAD_X   = 16;
  const PAD_Y   = 24;
  const LABEL_W = 100;
  const ARC_H   = 28;
  const ARROW   = 8;

  // ── 🔥 Utiliser l'ordre LLM du backend (via les nœuds) ──
  // Extraire l'ordre des flux depuis les nœuds eux-mêmes
  const flowOrderFromNodes: string[] = [];
  const seenFlows = new Set<string>();
  for (const node of graph.nodes) {
    const flow = node.business_flow || 'other';
    if (!seenFlows.has(flow)) {
      seenFlows.add(flow);
      flowOrderFromNodes.push(flow);
    }
  }

  // Si le backend a fourni un ordre (via flow_rank), on l'utilise
  // Sinon, on utilise l'ordre d'apparition dans les nœuds
  const FLOW_ORDER = flowOrderFromNodes.length > 0 
    ? flowOrderFromNodes 
    : ['authentication', 'dashboard', 'crud', 'search', 'reporting', 'settings', 'notifications', 'other'];

  const FLOW_LABELS: Record<string, string> = {
    authentication: 'Auth',
    dashboard:      'Dashboard',
    crud:           'CRUD',
    search:         'Search',
    reporting:      'Reporting',
    settings:       'Settings',
    notifications:  'Notifications',
    error_handling: 'Errors',
    monitoring:     'Monitor',
    api:            'API',
    testing:        'Testing',
    other:          'Other',
  };

  const FLOW_BAND_FILL: Record<string, string> = {
    authentication: '#eff6ff', dashboard:     '#f5f3ff',
    crud:           '#f0fdf4', search:        '#fff7ed',
    reporting:      '#fffbeb', settings:      '#f8fafc',
    notifications:  '#fdf4ff', error_handling: '#fef2f2',
    monitoring:     '#ecfeff', api:            '#f0fdf4',
    testing:        '#f5f3ff', other:         '#f9fafb',
  };

  const FLOW_BAND_TEXT: Record<string, string> = {
    authentication: '#1d4ed8', dashboard:     '#7c3aed',
    crud:           '#15803d', search:        '#c2410c',
    reporting:      '#b45309', settings:      '#475569',
    notifications:  '#9333ea', error_handling: '#dc2626',
    monitoring:     '#0891b2', api:            '#059669',
    testing:        '#7c3aed', other:         '#6b7280',
  };

  // ── Risk level priority order within a lane ──
  const RISK_RANK: Record<string, number> = {
    critical: 0, high: 1, medium: 2, low: 3,
  };

  const EDGE_COLORS: Record<string, string> = {
    requires: '#6366f1', blocks: '#ef4444', related: '#9ca3af',
  };

  // ── 🔥 Détection du flux : utiliser le champ business_flow du backend ──
  const detectFlow = (node: DependencyNode): string => {
    // Priorité 1 : Champ business_flow fourni par le backend (classification LLM)
    if (node.business_flow && node.business_flow !== 'other') {
      return node.business_flow;
    }
    
    // Priorité 2 : Vérifier si c'est vraiment "other" du LLM ou non classifié
    if (node.business_flow === 'other') {
      return 'other';
    }
    
    // Fallback : détection par mots-clés (si le backend n'a pas classifié)
    const FLOW_KEYWORDS: Record<string, string[]> = {
      authentication: ['auth', 'login', 'logout', 'register', 'signup', 'password', 'credential', 'session', 'token', 'sso', '2fa', 'mfa'],
      dashboard:      ['dashboard', 'home', 'overview', 'landing', 'summary', 'welcome', 'portal'],
      crud:           ['create', 'update', 'delete', 'edit', 'add', 'remove', 'save', 'crud', 'form', 'submit'],
      search:         ['search', 'filter', 'sort', 'query', 'find', 'browse', 'lookup'],
      reporting:      ['report', 'export', 'log', 'audit', 'history', 'analytics', 'metrics'],
      settings:       ['setting', 'config', 'preference', 'profile', 'account', 'permission', 'role'],
      notifications:  ['notification', 'alert', 'email', 'message', 'push', 'reminder'],
      error_handling: ['error', 'invalid', 'fail', 'reject', 'wrong', 'validation'],
      monitoring:     ['monitor', 'health', 'alert', 'track', 'activity', 'logging', 'performance'],
      api:            ['api', 'endpoint', 'swagger', 'documentation', 'rest', 'curl', 'integration'],
      testing:        ['test', 'automated', 'coverage', 'ci/cd', 'jest', 'playwright', 'pipeline'],
    };
    
    const text = (node.title ?? '').toLowerCase();
    for (const [flow, kws] of Object.entries(FLOW_KEYWORDS)) {
      if (kws.some(kw => text.includes(kw))) return flow;
    }
    return 'other';
  };

  // ── 1. Grouper les nœuds par flux ──
  const laneMap: Record<string, DependencyNode[]> = {};
  for (const node of graph.nodes) {
    const flow = detectFlow(node);
    laneMap[flow] = laneMap[flow] ?? [];
    laneMap[flow].push(node);
  }

  // Trier dans chaque lane par risque (Critical d'abord)
  for (const flow of FLOW_ORDER) {
    if (laneMap[flow]) {
      laneMap[flow].sort((a, b) => 
        (RISK_RANK[a.priority ?? 'low'] ?? 3) - (RISK_RANK[b.priority ?? 'low'] ?? 3)
      );
    }
  }

  // ── 2. Filtrer les lanes actives ──
  // 🔥 Utiliser l'ordre des flux du plan (FLOW_ORDER) mais seulement ceux qui ont des nœuds
  const activeLanes = FLOW_ORDER.filter(f => (laneMap[f]?.length ?? 0) > 0);
  
  // Ajouter les flux qui ne sont pas dans FLOW_ORDER mais qui ont des nœuds
  for (const flow of Object.keys(laneMap)) {
    if (!activeLanes.includes(flow)) {
      activeLanes.push(flow);
    }
  }

  const posById: Record<string, { x: number; y: number }> = {};
  const posNodes: GraphNodeLayout[] = [];
  const bands: LayerBand[] = [];

  // 🔥 Utiliser l'execution_order du backend
  const execOrder = graph.execution_order || [];

  // ── 3. Assigner les positions ──
  activeLanes.forEach((flow, li) => {
    const rowY = PAD_Y + li * (NODE_H + V_GAP);

    bands.push({
      y: rowY - V_GAP * 0.25,
      height: NODE_H + V_GAP * 0.5,
      label: FLOW_LABELS[flow] ?? flow.charAt(0).toUpperCase() + flow.slice(1),
      count: laneMap[flow].length,
      fill: FLOW_BAND_FILL[flow] ?? '#f9fafb',
      text_color: FLOW_BAND_TEXT[flow] ?? '#6b7280',
    });

    laneMap[flow].forEach((node, ni) => {
      const x = PAD_X + LABEL_W + ni * (NODE_W + H_GAP);
      const y = rowY;
      posById[node.id] = { x, y };

      // Position dans l'ordre d'exécution
      const execPos = execOrder.indexOf(node.tc_code) + 1;

      posNodes.push({
        id: node.id,
        tc_code: node.tc_code,
        title: (node.title ?? '').length > 24 
          ? (node.title ?? '').slice(0, 24) + '…' 
          : (node.title ?? ''),
        priority: node.priority ?? null,
        test_type: node.test_type ?? null,
        x,
        y,
        exec_pos: execPos > 0 ? execPos : li + 1,
      });
    });
  });

  // ── 4. Créer les arêtes ──
  const posEdges: GraphEdgeLayout[] = [];

  for (const edge of graph.edges) {
    const src = posById[edge.source_id];
    const tgt = posById[edge.target_id];
    if (!src || !tgt) continue;

    const srcNode = graph.nodes.find(n => n.id === edge.source_id);
    const tgtNode = graph.nodes.find(n => n.id === edge.target_id);
    const srcFlow = srcNode ? detectFlow(srcNode) : 'other';
    const tgtFlow = tgtNode ? detectFlow(tgtNode) : 'other';

    let path: string;
    let lx: number;
    let ly: number;

    if (srcFlow === tgtFlow) {
      // Même lane → flèche horizontale
      const x1 = src.x + NODE_W;
      const y1 = src.y + NODE_H / 2;
      const x2 = tgt.x - ARROW;
      const y2 = tgt.y + NODE_H / 2;
      path = `M ${x1} ${y1} L ${x2} ${y2}`;
      lx = (x1 + x2) / 2;
      ly = y1 - 10;
    } else {
      // Cross-lane → courbe de Bézier
      // Déterminer la direction : cible en dessous ou au-dessus de la source
      const goingDown = tgt.y >= src.y;
      const x1 = src.x + NODE_W / 2;
      const y1 = goingDown ? src.y + NODE_H : src.y;          // bas si descend, haut si monte
      const x2 = tgt.x + NODE_W / 2;
      const y2 = goingDown ? tgt.y - ARROW : tgt.y + NODE_H + ARROW; // haut si descend, bas si monte
      const cp1y = y1 + (y2 - y1) * 0.4;
      const cp2y = y1 + (y2 - y1) * 0.6;
      path = `M ${x1} ${y1} C ${x1} ${cp1y}, ${x2} ${cp2y}, ${x2} ${y2}`;
      lx = (x1 + x2) / 2;
      ly = (y1 + y2) / 2;
    }

    posEdges.push({
      path,
      label_x: lx,
      label_y: ly,
      source_code: edge.source,
      target_code: edge.target,
      dependency_type: edge.dependency_type || 'requires',
      color: EDGE_COLORS[edge.dependency_type] ?? '#9ca3af',
    });
  }

  // ── 5. Taille du canvas ──
  const maxPerLane = Math.max(...activeLanes.map(f => laneMap[f].length), 1);
  const svgW = PAD_X * 2 + LABEL_W + maxPerLane * (NODE_W + H_GAP) - H_GAP;
  const svgH = PAD_Y * 2 + activeLanes.length * (NODE_H + V_GAP) - V_GAP;

  console.log(
    `[GRAPH] ${posNodes.length} nodes, ${posEdges.length} edges, ${activeLanes.length} lanes`,
    'flows:', activeLanes,
    'order:', execOrder.slice(0, 5)
  );

  return {
    nodes: posNodes,
    edges: posEdges,
    svg_width: Math.max(svgW, 420),
    svg_height: Math.max(svgH, 180),
    bands,
  };
}
  // ── Node/edge colour helpers (used in SVG bindings) ───────────

  getNodeFill(priority: string | null): string {
    const m: Record<string, string> = {
      critical: '#fef2f2', high: '#fff7ed', medium: '#fefce8', low: '#f0fdf4',
    };
    return m[priority ?? ''] ?? '#f9fafb';
  }

  getNodeStroke(priority: string | null): string {
    const m: Record<string, string> = {
      critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#22c55e',
    };
    return m[priority ?? ''] ?? '#e5e7eb';
  }
}