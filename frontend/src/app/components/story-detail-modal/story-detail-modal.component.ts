import { Component, input, output, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { StoryWithVersion, UserStory, UserStoryVersion } from '../../models/user_story.model';
import { SpinnerComponent } from 'src/app/shared';

@Component({
  selector: 'app-story-detail-modal',
  standalone: true,
  imports: [CommonModule, ScoreBadgeComponent, SpinnerComponent],
  templateUrl: './story-detail-modal.component.html',
  styleUrl: './story-detail-modal.component.scss',
})
export class StoryDetailModalComponent {
  story = input<StoryWithVersion | null>(null);

  closed = output<void>();
  runPipeline = output<StoryWithVersion>();
  rerunPipeline = output<StoryWithVersion>();

  visible = computed(() => this.story() !== null);

  /**
   * Version à afficher (selected > latest)
   */
  displayVersion = computed(() => {
    const story = this.story();
    if (!story) return null;
    
    // Priorité à selected_version
    if (story.selected_version) return story.selected_version;
    
    // Sinon latest_version
    return story.latest_version ?? null;
  });

  /**
   * Vérifie si une version existe
   */
  hasVersion = computed(() => {
    return this.displayVersion() !== null;
  });

  /**
   * Vérifie si la version est approuvée
   */
  isApproved = computed(() => {
    const version = this.displayVersion();
    return version?.decision_status === 'approved';
  });

  /**
   * Vérifie si la version affichée est rejetée
   */
  isRejected = computed(() => {
    const version = this.displayVersion();
    return version?.decision_status === 'rejected';
  });

  /**
   * Vérifie si la version est en attente
   */
  isPending = computed(() => {
    const version = this.displayVersion();
    return version?.decision_status === 'pending';
  });

  /**
   * Vérifie si le pipeline est en cours
   */
  isProcessing = computed(() => {
    const story = this.story();
    return story?.agentStatus === 'processing';
  });

  /**
   * Vérifie si le pipeline est terminé avec succès
   */
  isCompleted = computed(() => {
    const story = this.story();
    return story?.agentStatus === 'completed';
  });

  /**
   * Vérifie si on peut lancer le pipeline
   */
  canRunPipeline = computed(() => {
    const story = this.story();
    if (!story) return false;
    if (this.isProcessing()) return false;
    return !story.version || ['completed', 'failed'].includes(story.agentStatus ?? '');
  });

  /**
   * Vérifie si on peut relancer le pipeline
   */
  canRerunPipeline = computed(() => {
    const story = this.story();
    if (!story) return false;
    if (this.isProcessing()) return false;
    return this.hasVersion() && this.canRunPipeline();
  });

  closeModal(): void {
    this.closed.emit();
  }

  onBackdropClick(event: MouseEvent): void {
    if ((event.target as HTMLElement).classList.contains('modal-backdrop')) {
      this.closeModal();
    }
  }

  onRunPipeline(): void {
    const s = this.story();
    if (s) {
      this.runPipeline.emit(s);
      this.closeModal();
    }
  }

  onRerunPipeline(): void {
    const s = this.story();
    if (s) {
      this.rerunPipeline.emit(s);
      this.closeModal();
    }
  }

  // ── Helpers ──

  getAcList(story: UserStory): string[] {
    const ac = story.acceptance_criteria;
    if (!ac) return [];
    return ac.filter(item => item && String(item).trim());
  }

  getImprovedAC(): string[] {
    const version = this.displayVersion();
    if (!version?.generated_acceptance_criteria) return [];
    return version.generated_acceptance_criteria.filter(
      item => item && String(item).trim()
    );
  }

  getOriginalScore(): number {
    const version = this.displayVersion();
    return version?.initial_score ?? 0;
  }

  getFinalScore(): number {
    const version = this.displayVersion();
    return version?.final_score ?? 0;
  }

  getDelta(): number {
    const version = this.displayVersion();
    if (!version) return 0;
    return (version.final_score ?? 0) - (version.initial_score ?? 0);
  }

  getTestabilityScore(): number | null {
    const version = this.displayVersion();
    return version?.testability_score ?? null;
  }

  isTestable(): boolean | null {
    const version = this.displayVersion();
    return version?.is_testable ?? null;
  }

  getTestabilityIssues(): string[] {
    const version = this.displayVersion();
    return version?.testability_issues ?? [];
  }

  formatScore(score: number | null | undefined): string {
    if (score == null || isNaN(score)) return '—';
    const display = score <= 1 ? score * 10 : score;
    return display.toFixed(1);
  }

  getScoreExplanation(): string | null {
    // Si vous avez une explication stockée quelque part
    const version = this.displayVersion();
    // Pour l'instant, retourne null
    return null;
  }

  /**
   * Métadonnées affichées
   */
  getMetadata(): { label: string; value: string }[] {
    const story = this.story();
    if (!story) return [];

    const meta: { label: string; value: string }[] = [];

    if (story.jira_status) meta.push({ label: 'Status', value: story.jira_status });
    if (story.priority) meta.push({ label: 'Priority', value: story.priority });
    if (story.issue_type) meta.push({ label: 'Type', value: story.issue_type });
    if (story.story_points) meta.push({ label: 'Points', value: String(story.story_points) });
    if (story.sprint) meta.push({ label: 'Sprint', value: story.sprint });
    if (story.assignee) meta.push({ label: 'Assignee', value: story.assignee });
    if (story.reporter) meta.push({ label: 'Reporter', value: story.reporter });
    if (story.epic_key) meta.push({ label: 'Epic', value: story.epic_key });
    if (story.fix_version) meta.push({ label: 'Fix Version', value: story.fix_version });
    if (story.agentStatus) meta.push({ label: 'Pipeline Status', value: this.getStatusLabel(story.agentStatus) });

    return meta;
  }

  private getStatusLabel(status: string): string {
    const labels: Record<string, string> = {
      'processing': 'Processing...',
      'completed': 'Completed',
      'failed': 'Failed'
    };
    return labels[status] || status;
  }

  /**
   * Version number (index + 1)
   */
  getVersionNumber(): number | null {
    const story = this.story();
    const version = this.displayVersion();
    if (!story || !version || !story.versions) return null;
    
    const index = story.versions.findIndex(v => v.id === version.id);
    return index >= 0 ? index + 1 : null;
  }

  /**
   * Total versions count
   */
  getVersionsCount(): number {
    return this.story()?.versions?.length ?? 0;
  }

  /**
   * Vérifie si c'est la meilleure version
   */
  isBestVersion(): boolean {
    const story = this.story();
    const version = this.displayVersion();
    if (!story || !version || !story.versions) return false;
    
    const bestScore = Math.max(...story.versions.map(v => v.final_score ?? 0));
    return (version.final_score ?? 0) === bestScore;
  }
}