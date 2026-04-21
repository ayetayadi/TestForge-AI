import { Component, OnInit, OnDestroy, inject, signal, computed, ViewChild, ElementRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Subscription } from 'rxjs';

import { PlaywrightE2EService, ExecutionReport } from '../../services/playwright-e2e.service';
import { ToastService } from '../../services/toast.service';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';

import {
  ScriptVersionUI,
  TestRunDetails,
  TestResultDetails,
  TestStepResult,
  TestResultStatus,
  StepStatus,
  ExecutionStep,
} from '../../models/playwright.models';
import { TestCaseService } from 'src/app/services/test-case.service';

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

  // Last run data
  lastRun = signal<TestRunDetails | null>(null);
  lastRunResult = signal<TestResultDetails | null>(null);
  lastRunSteps = signal<TestStepResult[]>([]);

  // UI state
  loading = signal(true);
  loadingContent = signal(false);
  isRunning = signal(false);
  activeTab = signal<'script' | 'run'>('script');

  // Execution config
  appUrl = signal('');
  browser = signal<'chromium' | 'firefox' | 'webkit'>('chromium');
  headless = signal(true);

  // SSE steps
  executionSteps = signal<ExecutionStep[]>([]);

  // For breadcrumb
  projectName = signal<string>('');
  issueKey = signal<string>('');
  testCaseCode = signal<string>('');

  // Nouveaux signals pour le rapport et le script v2
  executionReport = signal<ExecutionReport | null>(null);
  showReport = signal(false);
  newScriptGenerated = signal(false);
  newScriptContent = signal<string | null>(null);
  newScriptVersionNumber = signal<number | null>(null);

  private scriptV2Sub: Subscription | null = null;
  private executionReportSub: Subscription | null = null;
  private showSuccessToast = signal(false);
  public newScriptVersionId = signal<string | null>(null);

  currentTime = signal(new Date());
  private timeInterval: any;

  @ViewChild('terminalEl') terminalEl?: ElementRef<HTMLDivElement>;
  @ViewChild('reportEl') reportEl?: ElementRef<HTMLDivElement>;

  private stepsSub: Subscription | null = null;
  private executingSub: Subscription | null = null;

  readonly browsers: ('chromium' | 'firefox' | 'webkit')[] = ['chromium', 'firefox', 'webkit'];

  selectedVersion = computed(() =>
    this.scripts().find(s => s.id === this.selectedVersionId()) ?? null
  );

  placeholders = computed(() => {
    const content = this.selectedContent();
    if (!content) return [];
    return this.playwrightService.extractPlaceholders(content);
  });

  loadTestCaseInfo(testCaseId: string): void {
    this.testCaseService.getTestCaseById(testCaseId).subscribe({
      next: (testCase) => {
        this.projectName.set(testCase.project_name || '');
        this.issueKey.set(testCase.issue_key || '');
        this.testCaseCode.set(testCase.tc_code || '');
      },
      error: (err) => {
        console.error('Failed to load test case info:', err);
      }
    });
  }

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('testCaseId');
    if (!id) { 
      this.router.navigate(['/playwright-scripts']); 
      return; 
    }
    this.testCaseId.set(id);

    // Subscribe aux steps d'exécution
    this.stepsSub = this.playwrightService.executionSteps$.subscribe(steps => {
      this.executionSteps.set(steps);
      setTimeout(() => this.scrollToBottom(), 0);
    });

    // Subscribe aux nouveaux scripts v2
    this.setupScriptV2Listener();

    // Subscribe aux rapports d'exécution
    this.setupExecutionReportListener();

    this.loadTestCaseInfo(id);
    this.loadScripts();
    this.loadLastRun();
  }

  // Modifier loadLastRun pour qu'elle charge toujours les données
private loadLastRun(): void {
  if (!this.testCaseId()) return;
  
  this.playwrightService.getLastRun(this.testCaseId()).subscribe({
    next: (run) => {
      if (run.test_run) {
        this.lastRun.set(run.test_run);
        this.lastRunResult.set(run.result ?? null);
        this.lastRunSteps.set(run.steps ?? []);
        
        // ✅ Afficher le rapport si un run existe
        if (run.result) {
          this.showExecutionReport(run.result);
        }
      } else {
        // Pas de run, afficher l'état vide
        this.lastRun.set(null);
        this.lastRunResult.set(null);
        this.lastRunSteps.set([]);
      }
    },
    error: (err) => {
      console.error('Failed to load last run:', err);
      // Ne pas afficher d'erreur à l'utilisateur, juste garder l'état vide
    },
  });
}

// Méthode pour afficher le rapport à partir d'un résultat existant
private showExecutionReport(result: TestResultDetails): void {
  // Construire un rapport à partir des données existantes
  const report: ExecutionReport = {
    status: result.status === 'passed' ? 'passed' : (result.status === 'failed' ? 'failed' : 'partial'),
    totalSteps: (result.steps_passed || 0) + (result.steps_failed || 0),
    passedSteps: result.steps_passed || 0,
    failedSteps: result.steps_failed || 0,
    successRate: ((result.steps_passed || 0) / ((result.steps_passed || 0) + (result.steps_failed || 0))) * 100,
    duration: result.duration || 0,
    steps: this.lastRunSteps().map((step, idx) => ({
      order: idx + 1,
      type: step.type,
      description: step.content,
      status: step.status === 'success' ? 'success' : 'failed',
      error: step.error_message,
      duration: step.duration || 0
    })),
    placeholdersResolved: [],
    recommendations: result.status === 'passed' 
      ? ['✅ Test passed successfully!']
      : ['❌ Test failed. Check the error details above.']
  };
  
  this.executionReport.set(report);
  this.showReport.set(true);
}

  ngOnDestroy(): void {
    this.stepsSub?.unsubscribe();
    this.executingSub?.unsubscribe();
    this.scriptV2Sub?.unsubscribe();
    this.executionReportSub?.unsubscribe();
    this.playwrightService.stopStreaming();
    if (this.timeInterval) {
      clearInterval(this.timeInterval);
    }
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

        this.loadLastRun();
      },
      error: () => {
        this.toastService.error('Failed to load scripts');
        this.loading.set(false);
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
        
        // Réinitialiser l'indicateur de nouveau script si on sélectionne manuellement
        if (this.newScriptGenerated()) {
          this.newScriptGenerated.set(false);
        }
      },
      error: () => {
        this.toastService.error('Failed to load script content');
        this.loadingContent.set(false);
        this.loading.set(false);
      },
    });
  }


private setupScriptV2Listener(): void {
  this.scriptV2Sub = this.playwrightService.scriptV2$.subscribe(scriptV2 => {
    if (scriptV2 && scriptV2.content) {
      // Trouver la nouvelle version dans la liste
      const newVersion = this.scripts().find(s => s.source === 'v2_corrected');
      
      this.newScriptGenerated.set(true);
      this.newScriptContent.set(scriptV2.content);
      this.newScriptVersionNumber.set(newVersion?.versionNumber || null);
      this.newScriptVersionId.set(scriptV2.versionId);
      
      // ✅ Afficher une notification
      this.toastService.success('✨ New corrected script (v2) has been generated!');
      
      // ✅ NE PAS CHANGER D'ONGLET AUTOMATIQUEMENT
      // L'utilisateur reste sur l'onglet "Run" pour voir les résultats
      // Il pourra cliquer sur un bouton pour voir le nouveau script
      
      // Recharger les scripts en arrière-plan
      this.loadScripts();
      
      // ✅ Ajouter un bouton flottant ou dans le rapport
      this.showNewScriptButton.set(true);
    }
  });
}

// Ajouter ce signal
showNewScriptButton = signal(false);

// Méthode pour naviguer vers le nouveau script
viewNewScript(): void {
  if (this.newScriptVersionId()) {
    this.selectVersion(this.newScriptVersionId()!);
    this.activeTab.set('script');
    this.newScriptGenerated.set(false);
    this.showNewScriptButton.set(false);
    this.toastService.success('Now viewing the corrected script v2');
  }
}

  private setupExecutionReportListener(): void {
    this.executionReportSub = this.playwrightService.executionReport$.subscribe(report => {
      if (report) {
        this.executionReport.set(report);
        this.showReport.set(true);
        
        // Afficher un résumé dans la console
        console.log(`📊 Execution Report: ${report.status} - ${report.passedSteps}/${report.totalSteps} steps passed (${report.successRate.toFixed(1)}%)`);
        
        // Faire défiler jusqu'au rapport
        setTimeout(() => this.scrollToReport(), 500);
        
        // Afficher un toast avec le résumé
        if (report.status === 'passed') {
          this.toastService.success(`✅ Test passed! ${report.passedSteps}/${report.totalSteps} steps succeeded`);
        } else if (report.status === 'partial') {
          this.toastService.warning(`⚠️ Partial success: ${report.passedSteps}/${report.totalSteps} steps passed`);
        } else {
          this.toastService.error(`❌ Test failed: ${report.failedSteps} error(s) detected`);
        }
      }
    });
  }

  private highlightNewScript(): void {
    // Trouver le nouveau script dans la liste après reload
    setTimeout(() => {
      const newVersion = this.scripts().find(s => s.source === 'v2_corrected');
      if (newVersion) {
        // Sélectionner automatiquement le nouveau script
        this.selectVersion(newVersion.id);
        
        // Ajouter une animation de highlight
        const element = document.querySelector('.version-item.active');
        element?.classList.add('flash-highlight');
        setTimeout(() => element?.classList.remove('flash-highlight'), 2000);
      }
    }, 1000);
  }


  runScript(): void {
    const versionId = this.selectedVersionId();
    if (!versionId) return;

    // Réinitialiser les états
    this.isRunning.set(true);
    this.showReport.set(false);
    this.executionReport.set(null);
    this.newScriptGenerated.set(false);
    this.playwrightService.reset();
    this.activeTab.set('run');

    // Exécuter le script avec stream
    this.playwrightService.executeScriptWithStream({
      test_case_id: this.testCaseId(),
      script_version_id: versionId,
      app_url: this.appUrl() || undefined,
      browser: this.browser(),
      headless: this.headless()
    });

    // Surveiller la fin de l'exécution
    this.executingSub = this.playwrightService.isExecuting$.subscribe(executing => {
      if (!executing) {
        this.isRunning.set(false);
        this.loadLastRun();
        this.executingSub?.unsubscribe();
      }
    });
  }

  // Méthode pour appliquer/voir le nouveau script
  applyNewScript(): void {
    if (this.newScriptVersionId()) {
      this.selectVersion(this.newScriptVersionId()!);
      this.newScriptGenerated.set(false);
      this.activeTab.set('script');
      this.toastService.success('Now viewing the corrected script v2');
    }
  }

  // Méthode pour fermer le rapport
  closeReport(): void {
    this.showReport.set(false);
  }

  // Méthode pour ré-exécuter avec les mêmes paramètres
  rerunScript(): void {
    this.runScript();
  }

  private scrollToBottom(): void {
    const el = this.terminalEl?.nativeElement;
    if (el) el.scrollTop = el.scrollHeight;
  }

  private scrollToReport(): void {
    const el = this.reportEl?.nativeElement;
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }

  goBack(): void {
    this.router.navigate(['/test-cases', this.testCaseId()]);
  }

  getSourceLabel(source: string): string {
    const map: Record<string, string> = {
      v1_draft: 'v1 Draft',
      v2_corrected: 'v2 Corrected',
      manual_edit: 'Manual',
      ai_fix: 'AI Fix',
    };
    return map[source] ?? source;
  }

  getRunStatusClass(status: string | null | undefined): string {
    switch (status) {
      case TestResultStatus.PASSED: return 'badge-success';
      case TestResultStatus.FAILED: return 'badge-danger';
      case TestResultStatus.ERROR: return 'badge-warning';
      default: return 'badge-secondary';
    }
  }

  getStepTypeIcon(type: string): string {
    switch (type) {
      case 'think': return '🧠';
      case 'act':   return '⚡';
      default:      return '👁️';
    }
  }

  successStepsCount(): number {
    return this.lastRunSteps().filter(s => s.status === StepStatus.SUCCESS).length;
  }

  failedStepsCount(): number {
    return this.lastRunSteps().filter(s => s.status === StepStatus.FAILED).length;
  }

  getStepPreview(step: TestStepResult): string {
    const c = step.content || '';
    if (step.type === 'act') return c.length > 200 ? c.slice(0, 200) + '…' : c;
    const lines = c.split('\n').filter(l => l.trim());
    const preview = lines.slice(0, 4).join(' | ');
    return preview.length > 250 ? preview.slice(0, 250) + '…' : preview;
  }

  extractError(content: string): string {
    const lines = content.split('\n');
    const errLine = lines.find(l =>
      /timeouterror|exception|error:/i.test(l) || l.startsWith('### Error')
    );
    if (errLine) {
      const idx = lines.indexOf(errLine);
      return lines.slice(idx, idx + 3).join(' ').trim().slice(0, 300);
    }
    return content.slice(0, 200);
  }

  // Méthodes pour le rapport
  getReportStatusClass(): string {
    const report = this.executionReport();
    if (!report) return '';
    switch (report.status) {
      case 'passed': return 'report-passed';
      case 'failed': return 'report-failed';
      case 'partial': return 'report-partial';
      default: return '';
    }
  }

  getStatusIcon(): string {
    const report = this.executionReport();
    if (!report) return '';
    switch (report.status) {
      case 'passed': return '✓'; 
      case 'failed': return '✗';
      case 'partial': return '⚠';
      default: return '';
    }
  }
}