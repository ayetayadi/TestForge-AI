import {
  Component, OnInit, OnDestroy, inject, signal, computed, ViewChild, ElementRef
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import {
  PlaywrightE2EService, ExecutionReport, FullExecutionReport, RunHistoryItem
} from '../../services/playwright-e2e.service';
import { ToastService } from '../../services/toast.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { TestCaseService } from 'src/app/services/test-case.service';

import {
  ScriptVersionUI, TestRunDetails, TestResultDetails,
  TestStepResult, TestResultStatus, StepStatus, ExecutionStep,
} from '../../models/playwright.models';

@Component({
  selector: 'app-playwright-script-detail',
  standalone: true,
  imports: [CommonModule, FormsModule, SpinnerComponent],
  templateUrl: './playwright-script-detail.component.html',
  styleUrl: './playwright-script-detail.component.scss',
})
export class PlaywrightScriptDetailComponent implements OnInit, OnDestroy {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private playwrightService = inject(PlaywrightE2EService);
  private toastService = inject(ToastService);
  private testCaseService = inject(TestCaseService);

  testCaseId = signal<string>('');

  // Script data
  scripts = signal<ScriptVersionUI[]>([]);
  selectedVersionId = signal<string | null>(null);
  selectedContent = signal<string | null>(null);

  // Last run data (simple)
  lastRun = signal<TestRunDetails | null>(null);
  lastRunResult = signal<TestResultDetails | null>(null);
  lastRunSteps = signal<TestStepResult[]>([]);

  // Full report from backend
  fullReport = signal<FullExecutionReport | null>(null);
  isLoadingReport = signal(false);

  // Run history
  runHistory = signal<RunHistoryItem[]>([]);
  isLoadingHistory = signal(false);

  // Test case info (loaded on init, available before run)
  tcSteps = signal<any[]>([]);
  tcExpectedResults = signal<string[]>([]);
  tcTitle = signal<string>('');
  tcPriorityRaw = signal<string>('');

  // UI state
  loading = signal(true);
  loadingContent = signal(false);
  isRunning = signal(false);
  activeTab = signal<'script' | 'run'>('script');
  private reportAutoSwitched = false;

  // Execution config
  appUrl = signal('');
  browser = signal<'chromium' | 'firefox' | 'webkit'>('chromium');
  headless = signal(true);

  // SSE steps
  executionSteps = signal<ExecutionStep[]>([]);

  // Breadcrumb
  projectName = signal<string>('');
  issueKey = signal<string>('');
  testCaseCode = signal<string>('');

  // Inline editor
  isEditing = signal(false);
  isSavingEdit = signal(false);
  editContentStr = '';

  // Script generation
  isGenerating = signal(false);

  // Script v2
  executionReport = signal<ExecutionReport | null>(null);
  showReport = signal(false);
  newScriptGenerated = signal(false);
  newScriptContent = signal<string | null>(null);
  newScriptVersionNumber = signal<number | null>(null);
  showNewScriptButton = signal(false);
  newScriptVersionId = signal<string | null>(null);

  // ── Email dialog ──────────────────────────────────────────────────────────
  showEmailDialog = signal(false);
  emailRecipients = signal<string>('');
  isSendingEmail = signal(false);

  // ── Jira dialog ───────────────────────────────────────────────────────────
  showJiraDialog = signal(false);
  jiraProjectKey = signal<string>('');
  jiraPriority = signal<string>('High');
  isCreatingJira = signal(false);
  jiraCreated = signal<{ key: string } | null>(null);

  // ── Defect creation ───────────────────────────────────────────────────────
  isCreatingDefect = signal(false);

  // ── Report tab sections ───────────────────────────────────────────────────
  showReasoningSection = signal(true);
  showStepsSection = signal(true);
  showDefectSection = signal(true);
  showTcPlanSection = signal(true);
  showHistorySection = signal(false);

  currentTime = signal(new Date());
  private timeInterval: any;

  @ViewChild('terminalEl') terminalEl?: ElementRef<HTMLDivElement>;
  @ViewChild('reportEl') reportEl?: ElementRef<HTMLDivElement>;

  private stepsSub: Subscription | null = null;
  private executingSub: Subscription | null = null;
  private scriptV2Sub: Subscription | null = null;
  private executionReportSub: Subscription | null = null;

  readonly browsers: ('chromium' | 'firefox' | 'webkit')[] = ['chromium', 'firefox', 'webkit'];
  readonly jiraPriorities = ['Highest', 'High', 'Medium', 'Low', 'Lowest'];

  selectedVersion = computed(() =>
    this.scripts().find(s => s.id === this.selectedVersionId()) ?? null
  );

  placeholders = computed(() => {
    const content = this.selectedContent();
    if (!content) return [];
    return this.playwrightService.extractPlaceholders(content);
  });

  currentTestRunId = computed(() =>
    this.fullReport()?.test_run?.id ?? this.lastRun()?.id ?? null
  );

  currentDefect = computed(() => this.fullReport()?.defect ?? null);

  hasUserStory = computed(() => !!this.fullReport()?.test_case?.user_story_id);

  reportStatus = computed((): 'passed' | 'failed' | 'error' | 'unknown' => {
    const r = this.fullReport()?.result;
    if (!r) return 'unknown';
    return r.status as any;
  });

  failedSteps = computed(() =>
    (this.fullReport()?.steps ?? []).filter(s => s.status === 'failed')
  );

  thinkSteps = computed(() =>
    (this.fullReport()?.steps ?? []).filter(s => s.type === 'think')
  );

  actSteps = computed(() =>
    (this.fullReport()?.steps ?? []).filter(s => s.type !== 'think')
  );

  emailNotification = computed(() => {
    const runId = this.currentTestRunId();
    if (!runId) return null;
    try {
      const raw = localStorage.getItem('playwright_email_sent');
      if (!raw) return null;
      const map = JSON.parse(raw);
      return map[runId] ?? null;
    } catch {
      return null;
    }
  });

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('testCaseId');
    if (!id) { this.router.navigate(['/playwright-scripts']); return; }
    this.testCaseId.set(id);

    this.timeInterval = setInterval(() => this.currentTime.set(new Date()), 1000);

    this.stepsSub = this.playwrightService.executionSteps$.subscribe(steps => {
      this.executionSteps.set(steps);
      setTimeout(() => this.scrollToBottom(), 0);
    });

    this.scriptV2Sub = this.playwrightService.scriptV2$.subscribe(v2 => {
      if (v2?.content) {
        this.newScriptGenerated.set(true);
        this.newScriptContent.set(v2.content);
        this.newScriptVersionId.set(v2.versionId);
        this.showNewScriptButton.set(true);
        this.toastService.success('New corrected script (v2) generated!');
        this.loadScripts();
      }
    });

    this.executionReportSub = this.playwrightService.executionReport$.subscribe(report => {
      if (report) {
        this.executionReport.set(report);
        this.showReport.set(true);
        setTimeout(() => this.scrollToReport(), 500);
        if (report.status === 'passed') {
          this.toastService.success(`Test passed! ${report.passedSteps}/${report.totalSteps} steps`);
        } else {
          this.toastService.error(`Test failed: ${report.failedSteps} error(s)`);
        }
      }
    });

    this.executingSub = this.playwrightService.isExecuting$.subscribe(running => {
      if (!running && this.isRunning()) {
        this.isRunning.set(false);
        setTimeout(() => {
          this.loadLastRunAndReport();
          this.loadRunHistory();
        }, 1500);
      }
    });

    this.loadTestCaseInfo(id);
    this.loadScripts();
    this.loadRunHistory();
  }

  ngOnDestroy(): void {
    this.stepsSub?.unsubscribe();
    this.executingSub?.unsubscribe();
    this.scriptV2Sub?.unsubscribe();
    this.executionReportSub?.unsubscribe();
    this.playwrightService.stopStreaming();
    if (this.timeInterval) clearInterval(this.timeInterval);
  }

  // ── Data loading ──────────────────────────────────────────────────────────

  loadTestCaseInfo(id: string): void {
    this.testCaseService.getTestCaseById(id).subscribe({
      next: (tc) => {
        this.projectName.set(tc.project_name || '');
        this.issueKey.set(tc.issue_key || '');
        this.testCaseCode.set(tc.tc_code || '');
        this.tcTitle.set(tc.title || '');
        this.tcPriorityRaw.set(tc.priority || '');
        this.tcSteps.set(Array.isArray(tc.steps) ? tc.steps : []);
        this.tcExpectedResults.set(Array.isArray(tc.expected_results) ? tc.expected_results : []);
      },
    });
  }

  private loadScripts(): void {
    this.loading.set(true);
    this.playwrightService.getScripts(this.testCaseId()).subscribe({
      next: (response) => {
        const versions = this.playwrightService.convertToScriptVersionUI(response);
        this.scripts.set(versions);
        const active = versions.find(s => s.isActive) ?? versions[0] ?? null;
        if (active) {
          this.selectVersion(active.id);
        } else {
          this.loading.set(false);
        }
        this.loadLastRunAndReport(true);
      },
      error: () => {
        this.toastService.error('Failed to load scripts');
        this.loading.set(false);
      },
    });
  }

  private loadLastRunAndReport(switchTab = false): void {
    this.playwrightService.getLastRun(this.testCaseId()).subscribe({
      next: (run) => {
        if (run.test_run) {
          this.lastRun.set(run.test_run);
          this.lastRunResult.set(run.result ?? null);
          this.lastRunSteps.set(run.steps ?? []);
          this.loadFullReport(run.test_run.id, switchTab);
        }
      },
      error: () => {},
    });
  }

  loadFullReport(testRunId: string, switchTab = false): void {
    this.isLoadingReport.set(true);
    this.playwrightService.getFullReport(testRunId).subscribe({
      next: (report) => {
        this.fullReport.set(report);
        this.isLoadingReport.set(false);
        // Auto-switch to run tab on page load if there's a previous run (once only)
        if (switchTab && !this.reportAutoSwitched && report?.result) {
          this.reportAutoSwitched = true;
          this.activeTab.set('run');
        }
      },
      error: () => {
        this.isLoadingReport.set(false);
      },
    });
  }

  loadRunHistory(): void {
    this.isLoadingHistory.set(true);
    this.playwrightService.getRunsForTestCase(this.testCaseId()).subscribe({
      next: (res) => {
        this.runHistory.set(res.runs);
        this.isLoadingHistory.set(false);
      },
      error: () => {
        this.isLoadingHistory.set(false);
      },
    });
  }

  selectVersion(id: string): void {
    this.selectedVersionId.set(id);
    this.loadingContent.set(true);
    this.playwrightService.getScriptContent(id).subscribe({
      next: (res) => {
        this.selectedContent.set(res.content);
        this.loadingContent.set(false);
        this.loading.set(false);
      },
      error: () => {
        this.toastService.error('Failed to load script content');
        this.loadingContent.set(false);
        this.loading.set(false);
      },
    });
  }

  // ── Run actions ───────────────────────────────────────────────────────────

  runScript(): void {
    const versionId = this.selectedVersionId();
    if (!versionId) return;

    this.showReport.set(false);
    this.executionReport.set(null);
    this.fullReport.set(null);
    this.newScriptGenerated.set(false);
    this.playwrightService.reset();
    this.isRunning.set(true);
    this.activeTab.set('run');

    this.playwrightService.executeScriptWithStream({
      test_case_id: this.testCaseId(),
      script_version_id: versionId,
      app_url: this.appUrl() || undefined,
      browser: this.browser(),
      headless: this.headless(),
    });
  }

  rerunScript(): void {
    this.runScript();
  }

  enterEditMode(): void {
    this.editContentStr = this.selectedContent() ?? '';
    this.isEditing.set(true);
  }

  cancelEdit(): void {
    this.isEditing.set(false);
    this.editContentStr = '';
  }

  saveEdit(): void {
    const content = this.editContentStr.trim();
    if (!content) {
      this.toastService.error('Script cannot be empty');
      return;
    }
    const versionId = this.selectedVersionId();
    if (!versionId) return;

    this.isSavingEdit.set(true);
    this.playwrightService.updateScript(versionId, content).subscribe({
      next: (res) => {
        this.isSavingEdit.set(false);
        this.isEditing.set(false);
        this.editContentStr = '';
        this.toastService.success(`Saved as v${res.version_number}`);
        this.loadScripts(); // auto-selects the new active version
      },
      error: (err) => {
        this.isSavingEdit.set(false);
        this.toastService.error(err?.error?.detail ?? 'Failed to save script');
      },
    });
  }

  generateScript(): void {
    const tcId = this.testCaseId();
    if (!tcId) return;
    const url = this.appUrl() || undefined;
    this.isGenerating.set(true);
    this.playwrightService.generateScript({ test_case_id: tcId, app_url: url }).subscribe({
      next: (res) => {
        this.isGenerating.set(false);
        if (res.status === 'generated') {
          this.toastService.success(
            url ? `Script generated from live DOM (${res.placeholder_count} placeholders)`
                : `Script generated (${res.placeholder_count} placeholders)`
          );
          this.loadScripts();
        } else {
          this.toastService.error(res.error ?? 'Generation failed');
        }
      },
      error: (err) => {
        this.isGenerating.set(false);
        this.toastService.error(err?.message ?? 'Generation failed');
      },
    });
  }

  applyNewScript(): void {
    if (this.newScriptVersionId()) {
      this.selectVersion(this.newScriptVersionId()!);
      this.newScriptGenerated.set(false);
      this.activeTab.set('script');
      this.toastService.success('Now viewing the corrected script v2');
    }
  }

  viewNewScript(): void {
    this.applyNewScript();
  }

  loadHistoricRun(runId: string): void {
    this.loadFullReport(runId);
    this.activeTab.set('run');
  }

  // ── Email dialog ──────────────────────────────────────────────────────────

  openEmailDialog(): void {
    this.emailRecipients.set('');
    this.showEmailDialog.set(true);
  }

  closeEmailDialog(): void {
    this.showEmailDialog.set(false);
  }

  sendEmail(): void {
    const runId = this.currentTestRunId();
    if (!runId) {
      this.toastService.error('No test run found');
      return;
    }

    const raw = this.emailRecipients().trim();
    if (!raw) {
      this.toastService.error('Please enter at least one recipient');
      return;
    }

    const recipients = raw.split(/[,;\n]+/).map(r => r.trim()).filter(r => r.includes('@'));
    if (!recipients.length) {
      this.toastService.error('No valid email addresses found');
      return;
    }

    this.isSendingEmail.set(true);
    this.playwrightService.sendReportEmail(runId, recipients).subscribe({
      next: () => {
        this.isSendingEmail.set(false);
        this.showEmailDialog.set(false);
        this.toastService.success(`Report sent to ${recipients.length} recipient(s)`);
        try {
          const key = 'playwright_email_sent';
          const raw = localStorage.getItem(key);
          const map = raw ? JSON.parse(raw) : {};
          map[runId] = { sentAt: new Date().toISOString(), recipients };
          localStorage.setItem(key, JSON.stringify(map));
        } catch {}
      },
      error: (err) => {
        this.isSendingEmail.set(false);
        this.toastService.error('Failed to send email: ' + err.message);
      },
    });
  }

  // ── Jira dialog ───────────────────────────────────────────────────────────

  openJiraDialog(): void {
    this.jiraProjectKey.set('');
    this.jiraPriority.set('High');
    this.jiraCreated.set(null);
    this.showJiraDialog.set(true);
  }

  closeJiraDialog(): void {
    this.showJiraDialog.set(false);
  }

  createJiraIssue(): void {
    const defect = this.currentDefect();
    if (!defect) {
      this.toastService.error('No defect found. Run the test first.');
      return;
    }

    const projectKey = this.jiraProjectKey().trim().toUpperCase();
    if (!projectKey) {
      this.toastService.error('Please enter a Jira project key');
      return;
    }

    this.isCreatingJira.set(true);
    this.playwrightService.createJiraIssue(defect.id, projectKey, this.jiraPriority()).subscribe({
      next: (result) => {
        this.isCreatingJira.set(false);
        this.jiraCreated.set(result);
        const current = this.fullReport();
        if (current?.defect) {
          this.fullReport.set({
            ...current,
            defect: { ...current.defect, jira_issue_key: result.key },
          });
        }
        this.toastService.success(`Jira issue created: ${result.key}`);
      },
      error: (err) => {
        this.isCreatingJira.set(false);
        this.toastService.error('Failed to create Jira issue: ' + err.message);
      },
    });
  }

  // ── Defect creation ───────────────────────────────────────────────────────

  createDefect(): void {
    const runId = this.currentTestRunId();
    const tcId = this.testCaseId();
    if (!runId || !tcId) return;

    this.isCreatingDefect.set(true);
    this.playwrightService.createDefectFromRun(runId, tcId).subscribe({
      next: () => {
        this.isCreatingDefect.set(false);
        this.toastService.success('Defect created successfully');
        this.loadFullReport(runId);
      },
      error: (err) => {
        this.isCreatingDefect.set(false);
        this.toastService.error('Failed to create defect: ' + err.message);
      },
    });
  }

  // ── UI helpers ────────────────────────────────────────────────────────────

  closeReport(): void {
    this.showReport.set(false);
  }

  goBack(): void {
    this.router.navigate(['/test-cases', this.testCaseId()]);
  }

  getSourceLabel(source: string): string {
    const map: Record<string, string> = {
      v1_draft: 'v1 Draft', v2_corrected: 'v2 Corrected',
      manual_edit: 'Manual', ai_fix: 'AI Fix',
    };
    return map[source] ?? source;
  }

  getRunStatusClass(status: string | null | undefined): string {
    switch (status) {
      case 'passed': return 'badge-success';
      case 'failed': return 'badge-danger';
      case 'error': return 'badge-warning';
      default: return 'badge-secondary';
    }
  }

  getStepTypeIcon(type: string): string {
    return type === 'think' ? '🧠' : type === 'act' ? '⚡' : '👁️';
  }

  getStatusIcon(): string {
    switch (this.reportStatus()) {
      case 'passed': return '✓';
      case 'failed': return '✗';
      case 'error': return '⚠';
      default: return '●';
    }
  }

  getReportStatusLabel(): string {
    switch (this.reportStatus()) {
      case 'passed': return 'PASSED';
      case 'failed': return 'FAILED';
      case 'error': return 'ERROR';
      default: return 'UNKNOWN';
    }
  }

  getSeverityClass(severity: string): string {
    switch (severity) {
      case 'critical': return 'sev-critical';
      case 'high': return 'sev-high';
      case 'medium': return 'sev-medium';
      case 'low': return 'sev-low';
      default: return 'sev-medium';
    }
  }

  getDefectStatusLabel(status: string): string {
    switch ((status || '').toLowerCase()) {
      case 'open':        return 'Waiting for developer to fix';
      case 'in_progress': return 'Fix in progress';
      case 'closed':      return 'Fixed — ready for retest';
      default:            return status;
    }
  }

  getDefectStatusClass(status: string): string {
    switch ((status || '').toLowerCase()) {
      case 'open':        return 'defect-status--open';
      case 'in_progress': return 'defect-status--inprogress';
      case 'closed':      return 'defect-status--closed';
      default:            return '';
    }
  }

  getHistoryResultClass(status: string | null): string {
    switch (status) {
      case 'passed': return 'hist-passed';
      case 'failed': return 'hist-failed';
      case 'error':  return 'hist-error';
      default:       return 'hist-unknown';
    }
  }

  formatDuration(seconds: number | null): string {
    if (!seconds) return '—';
    if (seconds < 60) return `${seconds.toFixed(1)}s`;
    const m = Math.floor(seconds / 60);
    const s = Math.round(seconds % 60);
    return `${m}m ${s}s`;
  }

  successStepsCount(): number {
    return this.lastRunSteps().filter(s => s.status === StepStatus.SUCCESS).length;
  }

  failedStepsCount(): number {
    return this.lastRunSteps().filter(s => s.status === StepStatus.FAILED).length;
  }

  getStepPreview(step: TestStepResult): string {
    const c = step.content || '';
    const lines = c.split('\n').filter(l => l.trim());
    const preview = lines.slice(0, 4).join(' | ');
    return preview.length > 250 ? preview.slice(0, 250) + '…' : preview;
  }

  extractError(content: string): string {
    const lines = content.split('\n');
    const errLine = lines.find(l => /timeouterror|exception|error:/i.test(l));
    if (errLine) {
      const idx = lines.indexOf(errLine);
      return lines.slice(idx, idx + 3).join(' ').trim().slice(0, 300);
    }
    return content.slice(0, 200);
  }

  reasoningParagraphs(): string[] {
    const r = this.fullReport()?.llm_reasoning || '';
    return r.split('\n---\n').map(p => p.trim()).filter(p => p.length > 10);
  }

  private scrollToBottom(): void {
    const el = this.terminalEl?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  private scrollToReport(): void {
    const el = this.reportEl?.nativeElement;
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}
