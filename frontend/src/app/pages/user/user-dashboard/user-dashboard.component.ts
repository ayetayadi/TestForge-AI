import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import {
  DashboardService,
  DashboardStats,
  CoverageItem,
  PriorityItem,
  ActivityItem,
} from '../../../services/dashboard.service';

@Component({
  selector: 'app-user-dashboard',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './user-dashboard.component.html',
  styleUrls: ['./user-dashboard.component.scss'],
})
export class UserDashboardComponent implements OnInit {
  loading = true;
  error: string | null = null;
  stats: DashboardStats | null = null;

  constructor(private dashboardService: DashboardService) {}

  ngOnInit(): void {
    this.dashboardService.getStats().subscribe({
      next: (data) => {
        this.stats = data;
        this.loading = false;
      },
      error: (err) => {
        console.error('[Dashboard] Failed to load stats:', err);
        this.error = 'Failed to load dashboard data.';
        this.loading = false;
      },
    });
  }

  get coverageItems(): CoverageItem[] {
    return this.stats?.test_type_coverage ?? [];
  }

  get priorityItems(): PriorityItem[] {
    return this.stats?.priority_distribution ?? [];
  }

  get activities(): ActivityItem[] {
    return this.stats?.recent_activities ?? [];
  }

  /** Builds the conic-gradient CSS value from the priority distribution data. */
  get donutGradient(): string {
    const items = this.priorityItems;
    const total = items.reduce((s, i) => s + i.value, 0);
    if (!total) return '#e2e8f0 0deg 360deg';

    const colorMap: Record<string, string> = {
      red:    '#ef4444',
      orange: '#f59e0b',
      teal:   '#14b8a6',
      gray:   '#94a3b8',
    };

    let deg = 0;
    return items
      .map((item) => {
        const span = (item.value / total) * 360;
        const color = colorMap[item.color_class] ?? '#94a3b8';
        const segment = `${color} ${deg}deg ${deg + span}deg`;
        deg += span;
        return segment;
      })
      .join(', ');
  }

  /** Returns 'positive', 'negative', or 'neutral' class for weekly delta badges. */
  weeklyClass(count: number): string {
    return count > 0 ? 'positive' : 'neutral';
  }

  skeletonItems = [1, 2, 3, 4];
}
