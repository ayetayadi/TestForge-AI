import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { NgApexchartsModule } from 'ng-apexcharts';
import {
  DashboardService,
  DashboardStats,
  ProjectRow,
} from '../../../services/dashboard.service';
import { PaginationComponent } from '../../../components/pagination/pagination.component';

@Component({
  selector: 'app-user-dashboard',
  standalone: true,
  imports: [CommonModule, FormsModule, NgApexchartsModule, PaginationComponent],
  templateUrl: './user-dashboard.component.html',
  styleUrls: ['./user-dashboard.component.scss'],
})
export class UserDashboardComponent implements OnInit {
  loading = true;
  refreshing = false;
  error: string | null = null;
  stats: DashboardStats | null = null;

  // ── Table search + pagination ──────────────────────────────
  search = '';
  page = 1;
  pageSize = 5;

  // ── Pipeline funnel chart (the "courbe") ───────────────────
  funnelSeries: { name: string; data: number[] }[] = [];
  funnelChart = {
    type: 'area' as const,
    height: 280,
    toolbar: { show: false },
    fontFamily: 'inherit',
    sparkline: { enabled: false },
  };
  funnelStroke = { curve: 'smooth' as const, width: 3 };
  funnelFill = {
    type: 'gradient',
    gradient: { shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05, stops: [0, 90, 100] },
  };
  funnelColors = ['#6366f1'];
  funnelDataLabels = { enabled: true, style: { fontSize: '11px', fontWeight: 700 } };
  funnelMarkers = { size: 5, strokeWidth: 2, hover: { size: 7 } };
  funnelGrid = { borderColor: '#f0f0f0', strokeDashArray: 4 };
  funnelTooltip = { y: { formatter: (v: number) => v.toLocaleString() } };
  funnelXaxis: { categories: string[]; labels: { style: { fontSize: string } } } = {
    categories: ['User Stories', 'Refined', 'Risks', 'Plans', 'Suites', 'Test Cases', 'Executions'],
    labels: { style: { fontSize: '10px' } },
  };
  funnelYaxis = { labels: { style: { fontSize: '11px' } } };

  // ── Pass / Fail donut ──────────────────────────────────────
  donutSeries: number[] = [];
  donutLabels = ['Passed', 'Failed'];
  donutColors = ['#16a34a', '#dc2626'];
  donutChart = { type: 'donut' as const, height: 280, toolbar: { show: false }, fontFamily: 'inherit' };
  donutDataLabels = { enabled: false };
  donutPlotOptions = {
    pie: {
      donut: {
        size: '70%',
        labels: {
          show: true,
          name: { show: true, fontSize: '11px', fontWeight: 600 },
          value: { show: true, fontSize: '22px', fontWeight: 800 },
          total: {
            show: true,
            label: 'Pass Rate',
            fontSize: '10px',
            fontWeight: 600,
            color: '#6b7280',
            formatter: (w: any) => {
              const tot = w.globals.seriesTotals.reduce((a: number, b: number) => a + b, 0);
              const passed = w.globals.seriesTotals[0] ?? 0;
              return tot > 0 ? Math.round((passed / tot) * 100) + '%' : '0%';
            },
          },
        },
      },
    },
  };
  donutLegend = { position: 'bottom' as const, fontSize: '11px', fontWeight: 600 };
  donutTooltip = { y: { formatter: (v: number) => v.toLocaleString() } };
  donutResponsive = [{ breakpoint: 480, options: { chart: { height: 240 } } }];

  // ── Per-project comparison bar ─────────────────────────────
  barSeries: { name: string; data: number[] }[] = [];
  barChart = {
    type: 'bar' as const,
    height: 300,
    toolbar: { show: false },
    fontFamily: 'inherit',
    stacked: false,
  };
  barPlotOptions = { bar: { borderRadius: 4, columnWidth: '60%' } };
  barDataLabels = { enabled: false };
  barColors = ['#0d9488', '#0284c7', '#6366f1'];
  barLegend = { position: 'top' as const, fontSize: '11px', fontWeight: 600 };
  barTooltip = { y: { formatter: (v: number) => v.toLocaleString() } };
  barGrid = { borderColor: '#f0f0f0', strokeDashArray: 4 };
  barXaxis: { categories: string[]; labels: { style: { fontSize: string } } } = {
    categories: [],
    labels: { style: { fontSize: '10px' } },
  };
  barYaxis = { labels: { style: { fontSize: '11px' } } };

  constructor(private dashboardService: DashboardService) {}

  ngOnInit(): void {
    this.load();
  }

  load(isRefresh = false): void {
    isRefresh ? (this.refreshing = true) : (this.loading = true);
    this.error = null;

    this.dashboardService.getStats().subscribe({
      next: (data) => {
        this.stats = data;
        this.loading = false;
        this.refreshing = false;
        this.buildCharts(data);
      },
      error: (err) => {
        console.error('[Dashboard]', err);
        this.error = 'Failed to load dashboard data.';
        this.loading = false;
        this.refreshing = false;
      },
    });
  }

  private buildCharts(d: DashboardStats): void {
    // Pipeline funnel — global progression through the testing workflow.
    this.funnelSeries = [
      {
        name: 'Volume',
        data: [
          d.stories_count,
          d.refined_count,
          d.risks_count,
          d.test_plans_count,
          d.test_suites_count,
          d.test_cases_count,
          d.executions_count,
        ],
      },
    ];

    // Pass / Fail donut.
    this.donutSeries = [d.passed_count, d.failed_count];

    // Per-project comparison — top 8 by user-story volume.
    const top = [...d.projects].sort((a, b) => b.stories_count - a.stories_count).slice(0, 8);
    const cats = top.map((p) => p.project_key || p.project_name);
    this.barXaxis = { categories: cats, labels: { style: { fontSize: '10px' } } };
    this.barSeries = [
      { name: 'User Stories', data: top.map((p) => p.stories_count) },
      { name: 'Test Cases', data: top.map((p) => p.test_cases_count) },
      { name: 'Executions', data: top.map((p) => p.executions_count) },
    ];
  }

  // ── Table helpers ──────────────────────────────────────────
  get projects(): ProjectRow[] {
    return this.stats?.projects ?? [];
  }

  get filteredProjects(): ProjectRow[] {
    const term = this.search.trim().toLowerCase();
    if (!term) return this.projects;
    return this.projects.filter(
      (p) =>
        p.project_name.toLowerCase().includes(term) ||
        p.project_key.toLowerCase().includes(term)
    );
  }

  get pagedProjects(): ProjectRow[] {
    const start = (this.page - 1) * this.pageSize;
    return this.filteredProjects.slice(start, start + this.pageSize);
  }

  onSearch(val: string): void {
    this.search = val;
    this.page = 1;
  }

  // ── Rate calculations ──────────────────────────────────────
  passRate(p: ProjectRow): number {
    const total = p.passed_count + p.failed_count;
    return total > 0 ? Math.round((p.passed_count / total) * 100) : 0;
  }

  refinedRate(p: ProjectRow): number {
    return p.stories_count > 0
      ? Math.round((p.refined_count / p.stories_count) * 100)
      : 0;
  }

  passRateClass(p: ProjectRow): string {
    const r = this.passRate(p);
    if (p.passed_count + p.failed_count === 0) return 'rate--none';
    if (r >= 80) return 'rate--good';
    if (r >= 50) return 'rate--warn';
    return 'rate--danger';
  }

  get globalPassRate(): number {
    if (!this.stats) return 0;
    const total = this.stats.passed_count + this.stats.failed_count;
    return total > 0 ? Math.round((this.stats.passed_count / total) * 100) : 0;
  }

  get globalRefinedRate(): number {
    if (!this.stats || this.stats.stories_count === 0) return 0;
    return Math.round((this.stats.refined_count / this.stats.stories_count) * 100);
  }

  trackProject(_: number, p: ProjectRow): string {
    return p.project_id;
  }
}
