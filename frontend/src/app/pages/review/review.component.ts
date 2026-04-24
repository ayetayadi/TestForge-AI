import { Component, OnInit, OnDestroy, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { FormsModule } from '@angular/forms';
import { SpinnerComponent } from '../../shared/spinner/spinner.component';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { VersionsService, ToastService, PipelineService, SseService } from '../../services';
import { DecisionChoice, VersionState, SSEEvent, TraceEntry, UserStoryVersion, WorkflowStatus } from '../../models/user_story.model';
import { environment } from '../../../environments/environment';
import { NavigationService } from '../../services/navigation.service';

@Component({
  selector: 'app-review',
  standalone: true,
  imports: [CommonModule, SpinnerComponent, ScoreBadgeComponent, FormsModule],
  templateUrl: './review.component.html',
  styleUrls: ['./review.component.scss'],
})
export class ReviewComponent implements OnInit, OnDestroy {

  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private versionsService = inject(VersionsService);
  private toastService = inject(ToastService);
  private pipelineService = inject(PipelineService);
  private sseService = inject(SseService);
  private navigationService = inject(NavigationService);


  // Current version being viewed
  versionId = '';

  // Version state from API
  state = signal<VersionState | null>(null);

  // All versions for this story
  allVersions = signal<UserStoryVersion[]>([]);

  // Currently viewing version (can switch between versions)
  viewingVersionId = signal<string | null>(null);

  // UI states
  loading = signal(true);
  error = signal<string | null>(null);
  submitting = signal(false);
  decisionMade = signal(false);

  // Relaunch states
  relaunching = signal(false);
  relaunchPhase = signal<string>('');

  isEditingStory = signal(false);
  isEditingAC = signal(false);
  isSaving = signal(false);
  
  editableStory: string = '';
  editableAC: string[] = [];
  
  // Backup pour annuler
  private originalStoryBackup: string = '';
  private originalACBackup: string[] = [];

  // Processing step
  processingStep = signal<'processing' | 'done'>('done');
  phaseMessage = signal<string>('');

  // Navigation context
  private navProjectId: string | null = null;
  private navProjectName: string | null = null;
  private issueKey: string | null = null;

  // SSE subscription
  private sseSubscription: Subscription | null = null;

  // ─────────────────────────────────────────────
  // COMPUTED
  // ─────────────────────────────────────────────

  /**
   * Version actuellement affichée
   */
  currentVersion = computed(() => {
    const versions = this.allVersions();
    const viewingId = this.viewingVersionId();
    const state = this.state();
    
    if (viewingId) {
      const found = versions.find(v => v.id === viewingId);
      if (found) return found;
    }
    
    if (state?.version_id && versions.length > 0) {
      const found = versions.find(v => v.id === state.version_id);
      if (found) return found;
    }
    
    if (versions.length > 0) {
      return [...versions].sort((a, b) => 
        (a.started_at || '') > (b.started_at || '') ? -1 : 1
      )[0];
    }
    
    if (state && state.improved_story && state.version_id) {
      return {
        id: state.version_id,
        user_story_id: state.user_story_id || '',
        improved_story: state.improved_story,
        generated_acceptance_criteria: state.generated_acceptance_criteria || [],
        initial_score: state.initial_score || 0,
        final_score: state.final_score || 0,
        workflow_status: state.workflow_status as WorkflowStatus || 'completed',
        decision_status: 'pending',
        testability_score: state.testability_score,
        is_testable: state.is_testable,
        testability_issues: state.testability_issues || [],
        started_at: state.started_at,
        completed_at: state.completed_at,
      } as UserStoryVersion;
    }
    
    return null;
  });

  /**
   * Vérifie si on regarde la dernière version (la plus récente)
   */
  isViewingLatestVersion = computed(() => {
    const versions = this.allVersions();
    
    if (versions.length === 0) return true;
    
    const current = this.currentVersion();
    if (!current) return true;
    
    const latestVersion = versions[versions.length - 1];
    return current.id === latestVersion.id;
  });

  /**
   * Retourne le numéro de la version actuelle
   */
  getCurrentVersionNumber = computed(() => {
    const versions = this.allVersions();
    const current = this.currentVersion();
    
    if (!current || versions.length === 0) return 1;
    
    const index = versions.findIndex(v => v.id === current.id);
    return index >= 0 ? index + 1 : versions.length;
  });

  /**
   * Vérifie si la story a une décision FINALE
   */
  hasFinalDecision = computed(() => {
    const s = this.state();
    const decision = s?.decision_status;
    return decision === 'approved';
  });

  /**
   * Vérifie si on peut prendre une décision
   */
  canMakeDecision = computed(() => {
    const s = this.state();
    
    if (!s || s.workflow_status !== 'completed') return false;
    if (this.relaunching()) return false;
    if (this.decisionMade()) return false;

    const versionId = this.currentVersion()?.id;
    if (!versionId) return false;  
    return true;
  });

  /**
   * Meilleure version (score le plus élevé)
   */
  bestVersion = computed(() => {
    const versions = this.allVersions();
    if (!versions.length) return null;

    return versions.reduce((best, v) =>
      (v.final_score || 0) > (best.final_score || 0) ? v : best
    );
  });

  isBest(version: UserStoryVersion): boolean {
    return this.bestVersion()?.id === version.id;
  }

  /**
   * Version sélectionnée (approuvée)
   */
  selectedVersion = computed(() => {
    const versions = this.allVersions();
    return versions.find(v => v.decision_status === 'approved') ?? null;
  });

  /**
   * Nombre de versions
   */
  versionCount = computed(() => this.allVersions().length);

  // ─────────────────────────────────────────────
  // LIFECYCLE
  // ─────────────────────────────────────────────

  ngOnInit(): void {
    this.route.queryParams.subscribe(params => {
      this.navProjectId = params['projectId'] ?? null;
      this.navProjectName = params['projectName'] ?? null;
      this.issueKey = params['issueKey'] ?? null;
    });

    this.route.params.subscribe(params => {
      const versionId = params['versionId'];

      if (!versionId) {
        this.error.set("Missing versionId");
        this.loading.set(false);
        return;
      }

      this.versionId = versionId;
      this.resetState();
      this.loadVersion(this.versionId);
    });
  }

  ngOnDestroy(): void {
    this.cleanupSSE();
  }

  private resetState(): void {
    this.decisionMade.set(false);
    this.relaunching.set(false);
    this.relaunchPhase.set('');
    this.processingStep.set('done');
    this.viewingVersionId.set(null);
    this.allVersions.set([]);
  }

  // ─────────────────────────────────────────────
  // SSE MANAGEMENT
  // ─────────────────────────────────────────────

  private cleanupSSE(): void {
    if (this.sseSubscription) {
      this.sseSubscription.unsubscribe();
      this.sseSubscription = null;
    }
    if (this.versionId) {
      this.versionsService.disconnectFromVersionStream(this.versionId);
    }
  }

  private listenToStream(versionId: string): void {
    if (this.sseSubscription) return;

    console.log("[SSE CONNECT]", versionId);

    this.sseSubscription = this.versionsService.connectToVersionStream(versionId).subscribe({
      next: (event: SSEEvent) => {
        console.log("[SSE EVENT]", event.type, event.data);

        switch (event.type) {
          case 'processing':
            this.processingStep.set('processing');
            break;

          case 'phase':
            if (event.data?.message) {
              this.phaseMessage.set(event.data.message);
            }
            break;

          case 'completed':
            this.cleanupSSE();
            this.processingStep.set('done');
            this.phaseMessage.set('');
            this.loadVersion(versionId);
            break;

          case 'failed':
            this.cleanupSSE();
            this.processingStep.set('done');
            this.phaseMessage.set('');
            this.error.set('Pipeline failed');
            break;
        }
      },
      error: (err) => {
        console.error("[SSE ERROR]", err);
        this.cleanupSSE();
      }
    });
  }

  // ─────────────────────────────────────────────
  // LOAD VERSION & VERSIONS
  // ─────────────────────────────────────────────

  loadVersion(versionId: string): void {
    this.loading.set(true);
    this.error.set(null);

    this.versionsService.getVersion(versionId).subscribe({
      next: (versionState) => {
        console.log("[LOAD VERSION] Full response:", JSON.stringify(versionState, null, 2));

        if (versionState.workflow_status === 'not_found') {
          this.error.set('Version not found');
          this.loading.set(false);
          return;
        }

        this.state.set(versionState);

        if (!this.issueKey && versionState.issue_key) {
          this.issueKey = versionState.issue_key;
        }

        if (versionState.user_story_id) {
          this.loadVersions(versionState.user_story_id);
        } else {
          this.loading.set(false);
        }

        const WorkflowStatus = versionState.workflow_status;

        if (WorkflowStatus === 'processing') {
          this.processingStep.set('processing');
          this.listenToStream(versionId);
        } else {
          this.processingStep.set('done');
        }

        if (!this.navProjectId && versionState.project_id) {
          this.navProjectId = versionState.project_id;
        }
        if (!this.navProjectName && versionState.project_name) {
          this.navProjectName = versionState.project_name;
        }
      },
      error: (err) => {
        this.error.set(err.message || 'Failed to load version');
        this.loading.set(false);
      },
    });
  }

  /**
   * Charge toutes les versions d'une story
   */
  private loadVersions(storyId: string): void {
    fetch(`${environment.apiUrl}/user-stories/${storyId}/versions`)
      .then(res => {
        if (!res.ok) {
          console.warn(`[VERSIONS] HTTP ${res.status}`);
          return [];
        }
        return res.json();
      })
      .then((versions: any) => {
        const data = Array.isArray(versions)
          ? versions
          : versions?.data || versions?.versions || [];
        this.allVersions.set(data);
        this.loading.set(false);
      })
      .catch(err => {
        console.error("[VERSIONS ERROR]", err);
        this.allVersions.set([]);
        this.loading.set(false);
      });
  }

  // ─────────────────────────────────────────────
  // VERSION NAVIGATION
  // ─────────────────────────────────────────────

  viewVersion(version: UserStoryVersion): void {
    this.viewingVersionId.set(version.id);
  }

  viewLatestVersion(): void {
    const versions = this.allVersions();
    if (versions.length > 0) {
      const latest = versions[versions.length - 1];
      this.viewingVersionId.set(latest.id);
    } else {
      this.viewingVersionId.set(null);
    }
  }

  isViewing(version: UserStoryVersion): boolean {
    return this.currentVersion()?.id === version.id;
  }

  isLatest(index: number): boolean {
    return index === this.allVersions().length - 1;
  }

  // ─────────────────────────────────────────────
  // GETTERS - Story & Version Info
  // ─────────────────────────────────────────────

  getIssueKey(): string {
    return this.state()?.issue_key || this.state()?.jira_id || this.issueKey || 'Unknown';
  }

  getOriginalScore(): number {
    return this.currentVersion()?.initial_score ?? this.state()?.initial_score ?? 0;
  }

  getFinalScore(): number {
    return this.currentVersion()?.final_score ?? this.state()?.final_score ?? 0;
  }

  getDelta(): number {
    const v = this.currentVersion();
    if (!v) return 0;
    return (v.final_score ?? 0) - (v.initial_score ?? 0);
  }

  getOriginalStory(): string {
    const s = this.state();
    return s?.initial_story || s?.raw_story || '';
  }

  getImprovedStory(): string {
    return this.currentVersion()?.improved_story ?? this.state()?.improved_story ?? '';
  }

  getOriginalAC(): string[] {
    return this.parseAc(this.state()?.existing_ac);
  }

  getImprovedAC(): string[] {
    const version = this.currentVersion();
    if (version?.generated_acceptance_criteria) {
      return version.generated_acceptance_criteria;
    }
    return this.parseAc(this.state()?.generated_acceptance_criteria);
  }

  private parseAc(ac: string[] | string | undefined | null): string[] {
    if (!ac) return [];

    if (Array.isArray(ac)) {
      return ac.filter(item => item && String(item).trim());
    }

    if (typeof ac === 'string') {
      try {
        const parsed = JSON.parse(ac);
        if (Array.isArray(parsed)) return parsed;
      } catch {}

      return ac
        .split('\n')
        .map((x: string) => x.trim())
        .filter(Boolean);
    }

    return [];
  }

  // ─────────────────────────────────────────────
  // TRACE & HISTORY
  // ─────────────────────────────────────────────

  getScoreExplanation(): string | null {
    const trace = this.state()?.trace || [];

    for (let i = trace.length - 1; i >= 0; i--) {
      if (trace[i]?.data?.justification) {
        return trace[i].data!.justification!;
      }
    }

    return null;
  }

  getTrace(): TraceEntry[] {
    return this.state()?.trace || [];
  }

  getTraceScore(entry: TraceEntry): number | null {
    if (entry?.data?.final !== undefined) return entry.data.final;
    if (entry?.data?.current_score !== undefined) return entry.data.current_score;
    return null;
  }

  getTestabilityScore(): number | null {
    return (
      this.currentVersion()?.testability_score ??
      this.state()?.testability_score ??
      null
    );
  }

  isTestable(): boolean | null {
    return (
      this.currentVersion()?.is_testable ??
      this.state()?.is_testable ??
      null
    );
  }

  getTestabilityIssues(): string[] {
    return (
      this.currentVersion()?.testability_issues ??
      this.state()?.testability_issues ??
      []
    );
  }


  startEditingStory(): void {
  this.originalStoryBackup = this.getImprovedStory();
  this.editableStory = this.getImprovedStory();
  this.isEditingStory.set(true);
}

cancelEditingStory(): void {
  this.editableStory = this.originalStoryBackup;
  this.isEditingStory.set(false);
}

async saveStoryEdits(): Promise<void> {
  const versionId = this.currentVersion()?.id;
  if (!versionId) {
    this.toastService.error('No version found');
    return;
  }

  // Vérifier si des changements ont été faits
  if (this.editableStory === this.getImprovedStory()) {
    this.toastService.info('No changes detected');
    this.isEditingStory.set(false);
    return;
  }

  this.isSaving.set(true);

  try {
    // Garder les AC inchangées
    const currentAC = this.getImprovedAC();
    
    const result = await this.versionsService.editVersion(
      versionId,
      this.editableStory,
      currentAC
    ).toPromise();

    if (result?.status === 'success') {
      this.toastService.success('Story updated successfully');
      this.isEditingStory.set(false);
      // Recharger la version
      this.loadVersion(this.versionId);
    } else if (result?.status === 'no_change') {
      this.toastService.info('No changes detected');
      this.isEditingStory.set(false);
    } else {
      this.toastService.error('Failed to update story');
    }
  } catch (error: any) {
    if (error.status === 403) {
      this.toastService.error('Cannot edit an approved version');
    } else {
      this.toastService.error(error.message || 'Failed to update story');
    }
  } finally {
    this.isSaving.set(false);
  }
}

// ============================================================
// MÉTHODES POUR ACCEPTANCE CRITERIA
// ============================================================

startEditingAC(): void {
  this.originalACBackup = [...this.getImprovedAC()];
  this.editableAC = [...this.getImprovedAC()];
  this.isEditingAC.set(true);
}

cancelEditingAC(): void {
  this.editableAC = [...this.originalACBackup];
  this.isEditingAC.set(false);
}

async saveACEdits(): Promise<void> {
  const versionId = this.currentVersion()?.id;
  if (!versionId) {
    this.toastService.error('No version found');
    return;
  }

  // Vérifier si des changements ont été faits
  const currentAC = this.getImprovedAC();
  const hasChanges = JSON.stringify(this.editableAC) !== JSON.stringify(currentAC);
  
  if (!hasChanges) {
    this.toastService.info('No changes detected');
    this.isEditingAC.set(false);
    return;
  }

  this.isSaving.set(true);

  try {
    // Garder la story inchangée
    const currentStory = this.getImprovedStory();
    
    const result = await this.versionsService.editVersion(
      versionId,
      currentStory,
      this.editableAC
    ).toPromise();

    if (result?.status === 'success') {
      this.toastService.success('Criteria updated successfully');
      this.isEditingAC.set(false);
      // Recharger la version
      this.loadVersion(this.versionId);
    } else if (result?.status === 'no_change') {
      this.toastService.info('No changes detected');
      this.isEditingAC.set(false);
    } else {
      this.toastService.error('Failed to update criteria');
    }
  } catch (error: any) {
    if (error.status === 403) {
      this.toastService.error('Cannot edit an approved version');
    } else {
      this.toastService.error(error.message || 'Failed to update criteria');
    }
  } finally {
    this.isSaving.set(false);
  }
}



addAcceptanceCriterion(): void {
  this.editableAC = [...this.editableAC, 'New criterion...'];
}

removeAcceptanceCriterion(index: number): void {
  this.editableAC = this.editableAC.filter((_, i) => i !== index);
}

updateCriterion(index: number, value: string): void {
  const newAC = [...this.editableAC];
  newAC[index] = value;
  this.editableAC = newAC;
}

submitDecision(choice: DecisionChoice): void {
    if (!this.versionId || this.submitting() || !this.canMakeDecision()) return;

    const versionId = this.currentVersion()?.id;
    console.log("🚨 VERSION SENT:", versionId);

    if (!versionId) {
        this.toastService.error("No valid version found. Please wait.");
        return;
    }

    this.submitting.set(true);
    this.versionsService.sendDecision(versionId, choice).subscribe({
        next: (res) => {
            this.submitting.set(false);

            if (res.status === 'error') {
                this.toastService.error(res.message || 'Decision failed');
                return;
            }

            // ✅ NE PAS définir decisionMade pour 'relaunch'
            // Car on veut rester sur la page pour voir la nouvelle version
            if (choice !== 'relaunch') {
                this.decisionMade.set(true);
            }

            switch (choice) {
                case 'approve':
                    this.toastService.success('Version approved successfully');
                    this.navigateToStories();
                    break;

                case 'reject_keep':
                    this.toastService.info('Original version kept (AI suggestion rejected)');
                    this.navigateToStories();
                    break;

                case 'relaunch':
                    // ✅ Ne pas rediriger immédiatement
                    // ✅ Ne pas set decisionMade
                    this.handleRelaunch(res);
                    break;
            }
        },
        error: (err) => {
            this.submitting.set(false);
            this.toastService.error('Decision failed');
            console.error('[DECISION ERROR]', err);
        }
    });
}

private handleRelaunch(res: any): void {
    const newVersionId = res.new_version_id;

    if (!newVersionId) {
        this.toastService.error('Relaunch failed: no version_id');
        this.navigateToStories();
        return;
    }

    this.relaunching.set(true);
    this.relaunchPhase.set('Processing...');

    // ✅ Seulement connecter au SSE
    this.connectRelaunchSSE(newVersionId);
}

private connectRelaunchSSE(versionId: string): void {
    this.sseSubscription = this.versionsService.connectToVersionStream(versionId).subscribe({
        next: (event: SSEEvent) => {
            console.log('[SSE EVENT]', event.type, event.data);
            
            // Phase progress
            if (event.type === 'phase' && event.data?.message) {
                this.relaunchPhase.set(event.data.message);
            }

            // Écouter "version_created"
            if (event.type === 'version_created') {
                const newVersionId = event.data?.version_id;
                if (newVersionId) {
                    this.versionId = newVersionId;
                    this.loadVersion(newVersionId);
                    this.toastService.success('New version created');
                    this.relaunching.set(false);  // ✅ AJOUTER ICI
                    
                    const storyId = this.state()?.user_story_id;
                    if (storyId) {
                        this.loadVersions(storyId);
                    }
                }
            }
            
            // Événement completed
            if (event.type === 'completed') {
                const hasNewVersion = event.data?.has_new_version;
                
                if (hasNewVersion === false) {
                    this.toastService.info(event.data?.message || 'Already optimal');
                    this.relaunching.set(false);
                } else if (hasNewVersion === true) {
                    // ✅ Si nouvelle version créée, s'assurer que relaunching est false
                    this.relaunching.set(false);
                }
                
                const storyId = this.state()?.user_story_id;
                if (storyId) {
                    this.loadVersions(storyId);
                }
                
                this.cleanupSSE();
            }
            
            // Événement failed
            if (event.type === 'failed') {
                this.relaunching.set(false);
                this.toastService.error(event.data?.error || 'Pipeline failed');
                this.cleanupSSE();
            }
        },
        error: (err) => {
            console.error('[SSE ERROR]', err);
            this.relaunching.set(false);
            this.toastService.error('Connection lost');
            this.cleanupSSE();
        }
    });
}
  // ─────────────────────────────────────────────
  // NAVIGATION
  // ─────────────────────────────────────────────

// review.component.ts
private navigateToStories(): void {
    // Récupérer la page actuelle de la pagination
    const currentPage = this.navigationService.getCurrentPage() || 1;
    
    setTimeout(() => {
        this.router.navigate(['/user-stories'], {
            queryParams: {
                projectId: this.navProjectId,
                projectName: this.navProjectName,
                highlight: this.issueKey,
                page: currentPage  // ← AJOUTER la page
            }
        });
    }, 1000);
}
  goBack(): void {
    this.cleanupSSE();
    this.router.navigate(['/user-stories'], {
      queryParams: {
        projectId: this.navProjectId,
        projectName: this.navProjectName
      }
    });
  }

  // ─────────────────────────────────────────────
  // HELPERS
  // ─────────────────────────────────────────────

  formatScore(score: number | undefined | null): string {
    if (score === undefined || score === null || isNaN(score)) return '—';
    const displayScore = score <= 1 ? score * 10 : score;
    return displayScore.toFixed(1);
  }

  isVersionCompleted(): boolean {
    return this.state()?.workflow_status === 'completed';
  }

  isVersionFailed(): boolean {
    return this.state()?.workflow_status === 'failed';
  }

  isVersionProcessing(): boolean {
    return this.state()?.workflow_status === 'processing';
  }

formatDate(date: string | undefined | null): string {
  if (!date) return '';
  return new Date(date).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
}
}