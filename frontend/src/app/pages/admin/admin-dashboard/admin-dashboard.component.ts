import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import {
  AdminService,
  AdminAnalytics,
  TesterMetrics,
  ProjectMetrics,
} from 'src/app/services/admin.service';
import { NgApexchartsModule } from 'ng-apexcharts';
import { PaginationComponent } from '../../../components/pagination/pagination.component';

@Component({
  selector: 'app-admin-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, NgApexchartsModule, PaginationComponent],
  templateUrl: './admin-dashboard.component.html',
  styleUrls: ['./admin-dashboard.component.scss'],
})
export class AdminDashboardComponent implements OnInit {
  activeTab: 'testers' | 'projects' = 'testers';
  loading = false;
  refreshing = false;
  errorMessage = '';

  analytics: AdminAnalytics | null = null;
  expandedTester: string | null = null;

  testerSearch = '';

  // ── Pagination ────────────────────────────────────────────
  testerPage = 1;
  testerPageSize = 5;
  projectPage = 1;
  projectPageSize = 10;

  // ── Donut chart ───────────────────────────────────────────
  donutSeries: number[] = [];
  donutLabels: string[] = ['User Stories', 'Test Cases', 'Test Plans', 'Risks'];
  donutColors = ['#0d9488', '#0284c7', '#9333ea', '#ea580c'];
  donutChart = { type: 'donut' as const, height: 280, toolbar: { show: false }, fontFamily: 'inherit' };
  donutDataLabels = { enabled: false };
  donutPlotOptions = {
    pie: {
      donut: {
        size: '68%',
        labels: {
          show: true,
          name: { show: true, fontSize: '11px', fontWeight: 600 },
          value: { show: true, fontSize: '20px', fontWeight: 800 },
          total: {
            show: true,
            label: 'Total',
            fontSize: '11px',
            fontWeight: 600,
            color: '#6b7280',
            formatter: (w: any) =>
              String(w.globals.seriesTotals.reduce((a: number, b: number) => a + b, 0)),
          },
        },
      },
    },
  };
  donutLegend = { position: 'bottom' as const, fontSize: '11px', fontWeight: 600 };
  donutTooltip = { y: { formatter: (v: number) => v.toLocaleString() } };
  donutResponsive = [{ breakpoint: 480, options: { chart: { height: 240 } } }];

  // ── Bar chart ─────────────────────────────────────────────
  barSeries: { name: string; data: number[] }[] = [];
  barCategories: string[] = [];
  barChart = {
    type: 'bar' as const,
    height: 280,
    toolbar: { show: false },
    fontFamily: 'inherit',
    stacked: false,
  };
  barPlotOptions = { bar: { borderRadius: 4, columnWidth: '58%', dataLabels: { position: 'top' } } };
  barDataLabels = { enabled: false };
  barColors = ['#0d9488', '#0284c7', '#ea580c'];
  barLegend = { position: 'top' as const, fontSize: '11px', fontWeight: 600 };
  barTooltip = { y: { formatter: (v: number) => v.toLocaleString() } };
  barGrid = { borderColor: '#f0f0f0', strokeDashArray: 4, yaxis: { lines: { show: true } } };
  barXaxis: { categories: string[]; labels: { style: { fontSize: string } } } = {
    categories: [],
    labels: { style: { fontSize: '11px' } },
  };
  barYaxis = { labels: { style: { fontSize: '11px' } } };

  constructor(private adminService: AdminService, private router: Router) {}

  ngOnInit(): void {
    this.load();
  }

  load(isRefresh = false): void {
    isRefresh ? (this.refreshing = true) : (this.loading = true);
    this.errorMessage = '';

    this.adminService.getAnalytics().subscribe({
      next: (data) => {
        this.analytics = data;
        this.loading = false;
        this.refreshing = false;
        this.buildCharts(data);
      },
      error: (err) => {
        this.loading = false;
        this.refreshing = false;
        this.errorMessage = err.error?.detail || 'Failed to load analytics data';
      },
    });
  }

  private buildCharts(data: AdminAnalytics): void {
    const g = data.global;

    // Donut
    this.donutSeries = [
      g.total_stories,
      g.total_test_cases,
      g.total_test_plans,
      g.total_risks,
    ];

    // Bar — top 8 testers
    const top = data.testers.slice(0, 8);
    this.barCategories = top.map((t) => t.username);
    this.barXaxis = { categories: this.barCategories, labels: { style: { fontSize: '11px' } } };
    this.barSeries = [
      { name: 'User Stories', data: top.map((t) => t.total_stories) },
      { name: 'Test Cases',   data: top.map((t) => t.total_test_cases) },
      { name: 'Risks',        data: top.map((t) => t.total_risks) },
    ];
  }

  // ── Helpers ─────────────────────────────────────────────────────
  get global() { return this.analytics?.global; }

  get filteredTesters(): TesterMetrics[] {
    if (!this.analytics) return [];
    const term = this.testerSearch.toLowerCase();
    if (!term) return this.analytics.testers;
    return this.analytics.testers.filter(
      (t) => t.username.toLowerCase().includes(term) || t.email.toLowerCase().includes(term)
    );
  }

  get pagedTesters(): TesterMetrics[] {
    const start = (this.testerPage - 1) * this.testerPageSize;
    return this.filteredTesters.slice(start, start + this.testerPageSize);
  }

  get allProjects(): (ProjectMetrics & { tester: string; testerEmail: string; tester_active: boolean })[] {
    if (!this.analytics) return [];
    const result: (ProjectMetrics & { tester: string; testerEmail: string; tester_active: boolean })[] = [];
    for (const t of this.analytics.testers) {
      for (const p of t.projects) {
        result.push({ ...p, tester: t.username, testerEmail: t.email, tester_active: t.is_active });
      }
    }
    return result;
  }

  get pagedProjects() {
    const start = (this.projectPage - 1) * this.projectPageSize;
    return this.allProjects.slice(start, start + this.projectPageSize);
  }

  get maxStories(): number { return Math.max(1, ...this.allProjects.map((p) => p.story_count)); }
  get maxTesterStories(): number {
    if (!this.analytics) return 1;
    return Math.max(1, ...this.analytics.testers.map((t) => t.total_stories));
  }

  onTesterSearch(val: string): void {
    this.testerSearch = val;
    this.testerPage = 1;
  }

  toggleTester(id: string): void { this.expandedTester = this.expandedTester === id ? null : id; }
  initial(name: string): string  { return name ? name[0].toUpperCase() : '?'; }
  pct(val: number, total: number): number { return total > 0 ? Math.round((val / total) * 100) : 0; }
  barWidth(val: number, max: number): number { return max > 0 ? Math.round((val / max) * 100) : 0; }
  setTab(tab: 'testers' | 'projects'): void { this.activeTab = tab; }
  createUser(): void { this.router.navigate(['/admin/users']); }
  trackTester(_: number, t: TesterMetrics) { return t.id; }
  trackProject(_: number, p: ProjectMetrics) { return p.id; }
}
