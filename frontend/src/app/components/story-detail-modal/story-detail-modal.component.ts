import { Component, input, output, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { StoryWithJob, UserStory, UserStoryVersion } from '../../models';

@Component({
  selector: 'app-story-detail-modal',
  standalone: true,
  imports: [CommonModule, ScoreBadgeComponent],
  templateUrl: './story-detail-modal.component.html',
  styleUrl: './story-detail-modal.component.scss',
})
export class StoryDetailModalComponent {
  story = input<StoryWithJob | null>(null);

  closed = output<void>();
  runPipeline = output<StoryWithJob>();
  rerunPipeline = output<StoryWithJob>();

  visible = computed(() => this.story() !== null);

  /**
   * Version à afficher (selected > latest)
   */
getDisplayVersion(): UserStoryVersion | null {
  return this.story()?.display_version ?? null;
}

displayVersion = computed(() => this.story()?.display_version ?? null);

hasVersion(): boolean {
  return !!this.displayVersion();
}

  /**
   * Vérifie si la version est approuvée
   */
  isApproved(): boolean {
    const version = this.displayVersion();
    return version?.decision_status === 'approved';
  }

  /**
   * Vérifie si la version affichée es rejetée
   */
isRejected(): boolean {
  return this.getDisplayVersion()?.decision_status === 'rejected';
}

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
    const version = this.getDisplayVersion();
    if (!version?.generated_acceptance_criteria) return [];

    return version.generated_acceptance_criteria.filter(
      item => item && String(item).trim()
    );
  }

  formatScore(score: number | null | undefined): string {
    if (score == null || isNaN(score)) return '—';

    const display = score <= 1 ? score * 10 : score;
    return display.toFixed(1);
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

    return meta;
  }
} 