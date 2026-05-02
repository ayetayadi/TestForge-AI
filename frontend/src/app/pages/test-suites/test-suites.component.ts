import { Component, OnInit, inject, signal, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { lastValueFrom } from 'rxjs';

import { TestSuiteService } from '../../services/test-suite.service';
import { ProjectsService } from '../../services/projects.service';
import { ToastService } from '../../services/toast.service';
import { TestPlanService } from '../../services/test-plan.service';

import {
  TestSuiteListItem,
  SUITE_TYPE_CONFIG,
  SUITE_STATUS_CONFIG,
  PRIORITY_CONFIG,
} from '../../models/test-suite.model';
import { Project } from '../../models/user_story.model';
import { TestCaseService } from 'src/app/services/test-case.service';
import { TestCase } from 'src/app/models/test-case.model';

@Component({
  selector: 'app-test-suites',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule],
  templateUrl: './test-suites.component.html',
  styleUrl: './test-suites.component.scss',
})
export class TestSuitesComponent implements OnInit {
  private suiteService = inject(TestSuiteService);
  private projectsService = inject(ProjectsService);
  private router = inject(Router);
  private toast = inject(ToastService);
  private testCaseService = inject(TestCaseService);
  private testPlanService = inject(TestPlanService);

  // ── Data ─────────────────────────────────────────────────────
  allSuites = signal<TestSuiteListItem[]>([]);
  projects = signal<Project[]>([]);
  isLoading = signal(false);

  // ── Filters ───────────────────────────────────────────────────
  searchTerm = signal('');
  selectedProject = signal('');
  selectedType = signal('');
  selectedStatus = signal('');
  selectedPriority = signal('');
  viewMode = signal<'grid' | 'list'>('grid');

  // ── Generation ────────────────────────────────────────────────
  selectedPlanId = signal('');
  selectedStrategy = signal('risk_level');
  isGenerating = signal(false);
  availablePlans = signal<Array<{ id: string; title: string; test_case_count: number }>>([]);

  // ── Constants for template ────────────────────────────────────
  readonly SUITE_TYPE_CONFIG = SUITE_TYPE_CONFIG;
  readonly SUITE_STATUS_CONFIG = SUITE_STATUS_CONFIG;
  readonly PRIORITY_CONFIG = PRIORITY_CONFIG;

  readonly suiteTypes: { value: string; label: string }[] = [
    { value: '', label: 'All Types' },
    { value: 'feature', label: 'Feature' },
    { value: 'epic', label: 'Epic' },
    { value: 'sprint', label: 'Sprint' },
    { value: 'smoke', label: 'Smoke' },
    { value: 'regression', label: 'Regression' },
    { value: 'negative', label: 'Negative' },
    { value: 'security', label: 'Security' },
    { value: 'performance', label: 'Performance' },
    { value: 'e2e', label: 'E2E' },
  ];

  readonly priorities = ['', 'critical', 'high', 'medium', 'low'];
  readonly strategies = [
    { value: 'risk_level', label: 'By Risk Level' },
    { value: 'test_type', label: 'By Test Type' },
    { value: 'feature', label: 'By Feature' },
    { value: 'mixed', label: 'Mixed' },
  ];

  // ── Computed ──────────────────────────────────────────────────
  filteredSuites = computed(() => {
    let suites = this.allSuites();
    const q = this.searchTerm().toLowerCase().trim();
    const proj = this.selectedProject();
    const type = this.selectedType();
    const status = this.selectedStatus();
    const prio = this.selectedPriority();

    if (q) {
      suites = suites.filter(s =>
        s.title.toLowerCase().includes(q) ||
        (s.description?.toLowerCase() || '').includes(q) ||
        (s.project_name?.toLowerCase() || '').includes(q) ||
        (s.test_plan_title?.toLowerCase() || '').includes(q)
      );
    }
    if (proj) suites = suites.filter(s => s.project_name === proj);
    if (type) suites = suites.filter(s => s.suite_type === type);
    if (status) suites = suites.filter(s => s.status === status);
    if (prio) suites = suites.filter(s => s.priority === prio);

    return suites;
  });

  stats = computed(() => {
    const all = this.allSuites();
    return {
      total: all.length,
      active: all.filter(s => s.status === 'active').length,
      totalCases: all.reduce((sum, s) => sum + s.test_case_count, 0),
      aiGenerated: all.filter(s => s.is_ai_generated).length,
      criticalSuites: all.filter(s => s.priority === 'critical').length,
    };
  });

  canGenerate = computed(() => {
    return this.selectedPlanId() !== '';
  });

  // ── Lifecycle ─────────────────────────────────────────────────
  async ngOnInit() {
    await this.loadData();
  }

  async loadData() {
    this.isLoading.set(true);
    try {
      const [suitesRes, projectsRes] = await Promise.all([
        lastValueFrom(this.suiteService.getAll()),
        lastValueFrom(this.projectsService.getProjects()),
      ]);
      this.allSuites.set(suitesRes?.items ?? []);
      this.projects.set(projectsRes ?? []);

      // Charger les plans après avoir les projets
      await this.loadPlans();
    } catch {
      this.toast.error('Failed to load test suites');
    } finally {
      this.isLoading.set(false);
    }
  }

async loadPlans() {
  try {
    const allPlans: Array<{ id: string; title: string; test_case_count: number }> = [];

    for (const project of this.projects()) {
      try {
        const res = await lastValueFrom(
          this.testPlanService.getByProject(project.id)
        );

        for (const plan of res.items) {
          // ✅ Utiliser getTestCasesByPlan pour chaque plan
          let tcCount = 0;
          try {
            const tcs = await lastValueFrom(
              this.testCaseService.getTestCasesByPlan(plan.id)
            );
            tcCount = tcs?.length ?? 0;
          } catch {
            tcCount = 0;
          }

          allPlans.push({
            id: plan.id,
            title: plan.title,
            test_case_count: tcCount
          });
        }
      } catch {
        // Ignorer les projets sans plans
      }
    }

    this.availablePlans.set(allPlans);
  } catch (err) {
    console.warn('Could not load plans', err);
  }
}

private async fetchAllTestCases(): Promise<TestCase[]> {
  try {
    // Utiliser getTestCases avec un grand limit
    const tcs = await lastValueFrom(
      this.testCaseService.getTestCases({ limit: 5000 })
    );
    return tcs ?? [];
  } catch {
    console.warn('Could not fetch test cases');
    return [];
  }
}
  // ── Navigation ────────────────────────────────────────────────
  openSuite(id: string) {
    this.router.navigate(['/test-suites', id]);
  }

  // ── Generation ────────────────────────────────────────────────
  async generateSuites() {
    if (!this.selectedPlanId()) {
      this.toast.warning('Please select a Test Plan first');
      return;
    }

    this.isGenerating.set(true);
    try {
      const res = await lastValueFrom(this.suiteService.generate({
        test_plan_id: this.selectedPlanId(),
        strategy: this.selectedStrategy(),
        project_name: '',
      }));

      this.toast.success(`${res.count} suite(s) created successfully!`);
      
      // Recharger les données
      await this.loadData();
      
      // Réinitialiser la sélection
      this.selectedPlanId.set('');
    } catch (err: any) {
      const detail = err?.error?.detail || err?.message || 'Generation failed';
      this.toast.error(detail);
    } finally {
      this.isGenerating.set(false);
    }
  }

  // ── UI helpers ────────────────────────────────────────────────
  getSuiteTypeConfig(type?: string | null) {
    return type ? (SUITE_TYPE_CONFIG[type] ?? null) : null;
  }

  getStatusConfig(status: string) {
    return SUITE_STATUS_CONFIG[status] ?? { label: status, color: '#6b7280', bg: '#f3f4f6' };
  }

  getPriorityConfig(priority?: string | null) {
    return priority ? (PRIORITY_CONFIG[priority] ?? null) : null;
  }

  getCoverageColor(pct: number): string {
    if (pct >= 80) return '#10b981';
    if (pct >= 50) return '#f59e0b';
    return '#ef4444';
  }

  getCoverageLabel(pct: number): string {
    if (pct >= 80) return 'Good';
    if (pct >= 50) return 'Medium';
    return 'Low';
  }

  uniqueProjects(): string[] {
    return [...new Set(this.allSuites().map(s => s.project_name).filter(Boolean) as string[])];
  }

  trackById(_: number, item: TestSuiteListItem) {
    return item.id;
  }
}