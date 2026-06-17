import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';

import { PlaywrightE2EService } from '../../services/playwright-e2e.service';
import { JiraService } from '../../services/jira.service';
import { ToastService } from '../../services/toast.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { TestExecutionDetail, TestCaseResultDetail } from '../../models/playwright.models';

@Component({
  selector: 'app-execution-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, SpinnerComponent],
  templateUrl: './execution-detail.component.html',
  styleUrls: ['./execution-detail.component.scss'],
})
export class ExecutionDetailComponent implements OnInit {
  private route          = inject(ActivatedRoute);
  private router         = inject(Router);
  private playwrightSrv  = inject(PlaywrightE2EService);
  private jiraSrv        = inject(JiraService);
  private toast          = inject(ToastService);

  executionId   = signal<string>('');
  isLoading     = signal(true);
  execution     = signal<TestExecutionDetail | null>(null);
  expandedTcId  = signal<string | null>(null);

  // ── UI state ─────────────────────────────────────────────────────
  notified  = signal(false);

  // ── Notify modal ────────────────────────────────────────────────
  showNotifyModal       = signal(false);
  notifyRecipients      = signal('');
  notifyMethod          = signal<'email' | 'jira' | 'both'>('email');
  notifyIncludePassed   = signal(false);
  notifyIncludeSteps    = signal(true);
  notifyIncludeShots    = signal(true);
  notifyJiraProjectKey  = signal('');
  notifyJiraPriority    = signal<'Highest' | 'High' | 'Medium' | 'Low'>('High');
  jiraProjects          = signal<{ key: string; name: string }[]>([]);
  isSending             = signal(false);

  // ── Close modal ─────────────────────────────────────────────────
  showCloseModal = signal(false);
  isClosing      = signal(false);

  // ── Screenshot lightbox ─────────────────────────────────────────
  screenshotLightbox = signal<{ src: string; name: string } | null>(null);

  // ── Derived ─────────────────────────────────────────────────────
  hasFailures = computed(() => {
    const ex = this.execution();
    if (!ex) return false;
    return (ex.failed_count + ex.error_count) > 0;
  });

  isClosed = computed(() => this.execution()?.is_closed ?? false);

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('executionId') ?? '';
    this.executionId.set(id);
    this.notified.set(localStorage.getItem(`exec_${id}_notified`) === '1');
    this.loadDetail();
    this.loadJiraProjects();
  }

  loadDetail(): void {
    this.isLoading.set(true);
    this.playwrightSrv.getTestExecutionDetail(this.executionId()).subscribe({
      next: (detail) => {
        this.execution.set(detail);
        this.isLoading.set(false);
      },
      error: () => {
        this.toast.error('Failed to load execution details');
        this.isLoading.set(false);
      },
    });
  }

  private loadJiraProjects(): void {
    this.jiraSrv.getProjects().subscribe({
      next: (projects) => this.jiraProjects.set(
        (projects || []).map(p => ({ key: p.key, name: p.name }))
      ),
      error: () => this.jiraProjects.set([]),
    });
  }

  toggleTc(id: string): void {
    this.expandedTcId.set(this.expandedTcId() === id ? null : id);
  }

  goBack(): void {
    this.router.navigate(['/test-execution']);
  }

  openScript(testCaseId: string): void {
    this.router.navigate(['/playwright-scripts', testCaseId]);
  }

  getScriptBadgeLabel(tcr: TestCaseResultDetail): string {
    const src = tcr.script_source;
    if (!src) return 'No script';
    if (src === 'v2_corrected') return `v2 Corrected · v${tcr.script_version_number ?? '?'}`;
    const ph = tcr.script_placeholder_count ?? 0;
    if (ph > 0) return `v1 Draft · ${ph} placeholder${ph > 1 ? 's' : ''}`;
    return `v1 Draft · v${tcr.script_version_number ?? '?'}`;
  }

  getScriptBadgeClass(tcr: TestCaseResultDetail): string {
    const src = tcr.script_source;
    if (!src) return 'script-badge script-badge--none';
    if (src === 'v2_corrected') return 'script-badge script-badge--v2';
    const ph = tcr.script_placeholder_count ?? 0;
    return ph > 0 ? 'script-badge script-badge--v1-ph' : 'script-badge script-badge--v1';
  }

  // ── Notify developer ────────────────────────────────────────────
  openNotifyModal(): void {
    this.notifyRecipients.set('');
    this.notifyMethod.set('email');
    this.notifyIncludePassed.set(false);
    this.notifyIncludeSteps.set(true);
    this.notifyIncludeShots.set(true);
    this.notifyJiraProjectKey.set('');
    this.notifyJiraPriority.set('High');
    this.showNotifyModal.set(true);
  }

  closeNotifyModal(): void {
    this.showNotifyModal.set(false);
  }

  sendNotification(): void {
    const method = this.notifyMethod();
    const recipients = this.notifyRecipients()
      .split(/[,;\s]+/).map(s => s.trim()).filter(Boolean);

    if ((method === 'email' || method === 'both') && recipients.length === 0) {
      this.toast.error('Please enter at least one email address');
      return;
    }
    if ((method === 'jira' || method === 'both') && !this.notifyJiraProjectKey()) {
      this.toast.error('Please select a Jira project');
      return;
    }

    this.isSending.set(true);
    this.playwrightSrv.notifyDeveloper(this.executionId(), {
      recipients,
      method,
      include_passed: this.notifyIncludePassed(),
      include_steps: this.notifyIncludeSteps(),
      include_screenshots: this.notifyIncludeShots(),
      jira_project_key: this.notifyJiraProjectKey() || undefined,
      jira_priority: this.notifyJiraPriority(),
    }).subscribe({
      next: (res) => {
        this.isSending.set(false);
        this.showNotifyModal.set(false);
        this.notified.set(true);
        localStorage.setItem(`exec_${this.executionId()}_notified`, '1');

        const parts: string[] = [];
        if (res.emails_sent > 0) parts.push(`${res.emails_sent} email(s)`);
        if (res.jira_issues.length > 0) parts.push(`${res.jira_issues.length} Jira issue(s)`);
        this.toast.success(`Developer notified — ${parts.join(' · ') || 'done'}`);

        if (res.errors && res.errors.length > 0) {
          this.toast.error(`${res.errors.length} delivery error(s) — see console`);
          console.warn('Notify errors:', res.errors);
        }
      },
      error: (err) => {
        this.isSending.set(false);
        this.toast.error(err?.message || 'Failed to notify developer');
      },
    });
  }

  // ── Close suite ─────────────────────────────────────────────────
  openCloseModal(): void { this.showCloseModal.set(true); }
  cancelClose(): void    { this.showCloseModal.set(false); }

  confirmClose(): void {
    this.isClosing.set(true);
    this.playwrightSrv.closeExecution(this.executionId()).subscribe({
      next: () => {
        this.execution.update(ex => ex ? { ...ex, is_closed: true } : ex);
        this.isClosing.set(false);
        this.showCloseModal.set(false);
        this.toast.success('Suite execution closed');
      },
      error: () => {
        this.isClosing.set(false);
        this.toast.error('Failed to close execution');
      },
    });
  }

  reopenSuite(): void {
    this.playwrightSrv.reopenExecution(this.executionId()).subscribe({
      next: () => {
        this.execution.update(ex => ex ? { ...ex, is_closed: false } : ex);
        this.toast.success('Suite execution reopened');
      },
      error: () => {
        this.toast.error('Failed to reopen execution');
      },
    });
  }

  // ── Screenshot view / download ──────────────────────────────────
  private _screenshotName(tcr: TestCaseResultDetail): string {
    const raw = (tcr.tc_code || tcr.title || tcr.id || 'screenshot').toString();
    return `screenshot_${raw.replace(/[^\w.-]+/g, '_')}.png`;
  }

  openScreenshot(tcr: TestCaseResultDetail): void {
    if (!tcr.screenshot_b64) return;
    this.screenshotLightbox.set({
      src: 'data:image/png;base64,' + tcr.screenshot_b64,
      name: this._screenshotName(tcr),
    });
  }

  closeScreenshot(): void {
    this.screenshotLightbox.set(null);
  }

  downloadScreenshot(tcr: TestCaseResultDetail): void {
    if (!tcr.screenshot_b64) return;
    this._triggerDownload('data:image/png;base64,' + tcr.screenshot_b64, this._screenshotName(tcr));
  }

  downloadFromLightbox(): void {
    const lb = this.screenshotLightbox();
    if (lb) this._triggerDownload(lb.src, lb.name);
  }

  private _triggerDownload(dataUrl: string, filename: string): void {
    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  // ── Execution log report (styled PDF) ───────────────────────────
  isDownloadingReport = signal(false);

  /**
   * Télécharge un rapport PDF stylé de l'exécution : pour chaque cas de test,
   * tous les steps exécutés (réussis ou échoués) et, pour les échecs, le
   * raisonnement (justification) + le message d'erreur. Généré côté backend.
   */
  downloadReport(): void {
    const ex = this.execution();
    if (!ex) return;

    this.isDownloadingReport.set(true);
    this.playwrightSrv.exportExecutionReportPdf(ex.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const safe = (ex.suite_title || 'execution').replace(/[^\w.-]+/g, '_');
        this._triggerDownload(url, `report_${safe}_${ex.id.slice(0, 8)}.pdf`);
        URL.revokeObjectURL(url);
        this.isDownloadingReport.set(false);
        this.toast.success('Report downloaded');
      },
      error: () => {
        this.isDownloadingReport.set(false);
        this.toast.error('Failed to generate PDF report');
      },
    });
  }

  // ── UI helpers ──────────────────────────────────────────────────
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
    return new Date(iso).toLocaleString();
  }
}
