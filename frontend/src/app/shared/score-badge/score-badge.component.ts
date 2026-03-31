import { Component, Input, computed } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-score-badge',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './score-badge.component.html',
  styleUrl: './score-badge.component.scss',
})
export class ScoreBadgeComponent {
  @Input() score: number = 0;
  @Input() delta?: number;
  @Input() size: 'small' | 'medium' | 'large' = 'medium';


  scoreNormalized = computed(() => {
  return this.score <= 1 ? this.score * 10 : this.score;
});

scoreClass = computed(() => {
  const score = this.scoreNormalized();

  let level = 'poor';
  if (score >= 8) level = 'excellent';
  else if (score >= 6) level = 'good';
  else if (score >= 4) level = 'fair';

  return `${level} ${this.size}`;
});

  get colorClass() {
  const score = this.score <= 1 ? this.score * 10 : this.score;

  if (score >= 8) return 'high';
  if (score >= 5) return 'medium';
  return 'low';
}

}