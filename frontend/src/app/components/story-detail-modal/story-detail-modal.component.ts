import { Component, input, output, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ScoreBadgeComponent } from '../../shared/score-badge/score-badge.component';
import { UserStory } from '../../models';

@Component({
  selector: 'app-story-detail-modal',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './story-detail-modal.component.html',
  styleUrl: './story-detail-modal.component.scss',
})
export class StoryDetailModalComponent {
  story = input<UserStory | null>(null);

  closed = output<void>();
  runPipeline = output<UserStory>();
  rerunPipeline = output<UserStory>();

  visible = computed(() => this.story() !== null);

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
    if (Array.isArray(ac)) return ac.filter(item => item && String(item).trim());
    if (typeof ac === 'string') return ac.split('\n').filter(line => line.trim());
    return [];
  }

  getImprovedAC(): string[] {
    const story = this.story();
    if (!story?.final?.acceptance_criteria) return [];
    const ac = story.final.acceptance_criteria;
    if (Array.isArray(ac)) return ac;
    if (typeof ac === 'string') {
      try {
        const parsed = JSON.parse(ac);
        return Array.isArray(parsed) ? parsed : [];
      } catch {
        return (ac as string).split('\n').filter(l => l.trim());
      }
    }
    return [];
  }

  formatScore(score: number | null | undefined): string {
    if (score == null || isNaN(score)) return '—';
    const display = score <= 1 ? score * 10 : score;
    return display.toFixed(1);
  }

  getMetadata(): { label: string; value: string }[] {
    const story = this.story();
    if (!story) return [];

    const meta: { label: string; value: string }[] = [];

    if (story.status) meta.push({ label: 'Status', value: story.status });
    if (story.priority) meta.push({ label: 'Priority', value: story.priority });
    if (story.issue_type) meta.push({ label: 'Type', value: story.issue_type });
    if (story.story_points) meta.push({ label: 'Points', value: String(story.story_points) });
    if (story.sprint) meta.push({ label: 'Sprint', value: story.sprint });
    if (story.assignee) meta.push({ label: 'Assignee', value: story.assignee });
    if (story.reporter) meta.push({ label: 'Reporter', value: story.reporter });
    if (story.epic_name) meta.push({ label: 'Epic', value: story.epic_name });
    if (story.fix_version) meta.push({ label: 'Fix Version', value: story.fix_version });

    return meta;
  }
}
