import {
  Component, OnInit, OnDestroy, inject, signal, computed
} from '@angular/core';
import { CommonModule, DecimalPipe, SlicePipe, UpperCasePipe } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { FormsModule } from '@angular/forms';

import {
  PlaywrightE2EService,
  TestRunListItem,
  TestRunsListResponse
} from '../../services/playwright-e2e.service';
import { ToastService } from '../../services/toast.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';

const EMAIL_STORAGE_KEY = 'playwright_email_sent';

@Component({
  selector: 'app-execution-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, SpinnerComponent, RouterLink],
  templateUrl: './execution-dashboard.component.html',
  styleUrl: './execution-dashboard.component.scss',
})
export class ExecutionDashboardComponent implements OnInit, OnDestroy {
  private playwrightService = inject(PlaywrightE2EService);
  private toastService = inject(ToastService);
  private router = inject(Router);

  // Data
  runs = signal<TestRunListItem[]>([]);
  stats = signal<TestRunsListResponse['stats']>({
    total: 0, passed: 0, failed: 0, skipped: 0, running: 0,
    pass_rate: 0, avg_duration: 0,
  });
  total = signal(0);

  // UI state
  loading = signal(true);
  resultFilter = signal<string>('all');
  currentPage = signal(0);
  pageSize = 20;

  // Email sent tracking (localStorage)
  emailSentMap = signal<Record<string, { sentAt: string; recipients: string[] }>>({});

  // Computed
  filteredRuns = computed(() => this.runs());

  awaitingFixRuns = computed(() =>
    this.runs().filter(r =>
      r.defect &&
      r.defect.status === 'open' &&
      this.isEmailSent(r.id)
    )
  );

  passedRuns = computed(() => this.runs().filter(r => r.result_status === 'passed'));
  failedRuns = computed(() => this.runs().filter(r => r.result_status === 'failed' || r.result_status === 'error'));
  runningRuns = computed(() => this.runs().filter(r => r.status === 'running'));

  totalPages = computed(() => Math.ceil(this.total() / this.pageSize));

  ngOnInit(): void {
    this.loadEmailSentMap();
    this.loadRuns();
  }

  ngOnDestroy(): void {}

  // ----------------------------------------------------------------
  // Load
  // ----------------------------------------------------------------

  loadRuns(): void {
    this.loading.set(true);
    this.playwrightService.getTestRunsList({
      limit: this.pageSize,
      offset: this.currentPage() * this.pageSize,
      resultFilter: this.resultFilter() !== 'all' ? this.resultFilter() : undefined,
    }).subscribe({
      next: (data) => {
        this.runs.set(data.runs);
        this.stats.set(data.stats);
        this.total.set(data.total);
        this.loading.set(false);
      },
      error: () => {
        this.toastService.error('Failed to load execution history');
        this.loading.set(false);
      },
    });
  }

  // ----------------------------------------------------------------
  // Filters & pagination
  // ----------------------------------------------------------------

  setFilter(filter: string): void {
    this.resultFilter.set(filter);
    this.currentPage.set(0);
    this.loadRuns();
  }

  prevPage(): void {
    if (this.currentPage() > 0) {
      this.currentPage.update(p => p - 1);
      this.loadRuns();
    }
  }

  nextPage(): void {
    if (this.currentPage() < this.totalPages() - 1) {
      this.currentPage.update(p => p + 1);
      this.loadRuns();
    }
  }

  // ----------------------------------------------------------------
  // Navigation
  // ----------------------------------------------------------------

  viewScriptDetail(run: TestRunListItem): void {
    if (run.test_case?.id) {
      this.router.navigate(['/playwright-scripts', run.test_case.id]);
    }
  }

  // ----------------------------------------------------------------
  // Email tracking (localStorage)
  // ----------------------------------------------------------------

  private loadEmailSentMap(): void {
    try {
      const raw = localStorage.getItem(EMAIL_STORAGE_KEY);
      if (raw) this.emailSentMap.set(JSON.parse(raw));
    } catch {}
  }

  isEmailSent(testRunId: string): boolean {
    return !!this.emailSentMap()[testRunId];
  }

  getEmailInfo(testRunId: string): { sentAt: string; recipients: string[] } | null {
    return this.emailSentMap()[testRunId] ?? null;
  }

  markEmailSent(testRunId: string, recipients: string[]): void {
    const map = { ...this.emailSentMap() };
    map[testRunId] = { sentAt: new Date().toISOString(), recipients };
    this.emailSentMap.set(map);
    try { localStorage.setItem(EMAIL_STORAGE_KEY, JSON.stringify(map)); } catch {}
  }

  // ----------------------------------------------------------------
  // Helpers
  // ----------------------------------------------------------------

  formatDuration(seconds: number | null): string {
    if (!seconds) return '—';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }

  formatDate(iso: string | null): string {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('fr-FR', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  }

  getBrowserIcon(browser: string): string {
    const icons: Record<string, string> = {
      chromium: '🌐',
      firefox: '🦊',
      webkit: '🧭',
    };
    return icons[browser] ?? '🌐';
  }

  getSeverityClass(severity: string): string {
    const classes: Record<string, string> = {
      critical: 'sev-critical',
      high: 'sev-high',
      medium: 'sev-medium',
      low: 'sev-low',
      trivial: 'sev-trivial',
    };
    return classes[severity] ?? 'sev-medium';
  }

  getDefectStatusClass(status: string): string {
    const classes: Record<string, string> = {
      open: 'defect-open',
      in_progress: 'defect-inprogress',
      resolved: 'defect-resolved',
      closed: 'defect-closed',
      reopened: 'defect-reopened',
    };
    return classes[status] ?? 'defect-open';
  }

  getResultIcon(status: string | null): string {
    const icons: Record<string, string> = {
      passed: '✅',
      failed: '❌',
      error: '⚠️',
      skipped: '⏭️',
    };
    return status ? (icons[status] ?? '•') : '⏳';
  }

  getPriorityClass(priority: string | null): string {
    const map: Record<string, string> = {
      critical: 'pri-critical',
      high: 'pri-high',
      medium: 'pri-medium',
      low: 'pri-low',
    };
    return priority ? (map[priority] ?? 'pri-medium') : 'pri-medium';
  }

  trackByRunId(_: number, run: TestRunListItem): string {
    return run.id;
  }
}
