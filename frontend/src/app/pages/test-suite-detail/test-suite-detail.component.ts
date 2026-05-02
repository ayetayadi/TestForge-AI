import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';

import { TestSuiteService } from '../../services/test-suite.service';
import { ToastService } from '../../services/toast.service';

import {
  TestSuiteDetail,
  DependencyNode,
  DependencyEdge,
  SUITE_TYPE_CONFIG,
  SUITE_STATUS_CONFIG,
  PRIORITY_CONFIG,
} from '../../models/test-suite.model';

type DetailTab = 'overview' | 'cases' | 'traceability' | 'graph';

@Component({
  selector: 'app-test-suite-detail',
  standalone: true,
  imports: [CommonModule, RouterModule, FormsModule],
  templateUrl: './test-suite-detail.component.html',
  styleUrl: './test-suite-detail.component.scss',
})
export class TestSuiteDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private service = inject(TestSuiteService);
  private toast = inject(ToastService);

  // ── State ─────────────────────────────────────────────────────
  suite = signal<TestSuiteDetail | null>(null);
  isLoading = signal(true);
  activeTab = signal<DetailTab>('overview');
  expandedCase = signal<string | null>(null);

  // ── Constants ─────────────────────────────────────────────────
  readonly SUITE_TYPE_CONFIG = SUITE_TYPE_CONFIG;
  readonly SUITE_STATUS_CONFIG = SUITE_STATUS_CONFIG;
  readonly PRIORITY_CONFIG = PRIORITY_CONFIG;

  readonly tabs: { id: DetailTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'cases', label: 'Test Cases' },
    { id: 'traceability', label: 'Traceability Matrix' },
    { id: 'graph', label: 'Dependency Graph' },
  ];

  // ── Computed ──────────────────────────────────────────────────
  get suiteData(): TestSuiteDetail | null {
    return this.suite();
  }

  // ── Lifecycle ─────────────────────────────────────────────────
  async ngOnInit() {
    const id = this.route.snapshot.paramMap.get('suiteId');
    if (!id) {
      this.router.navigate(['/test-suites']);
      return;
    }

    await this.loadSuite(id);
  }

  async loadSuite(id: string) {
    this.isLoading.set(true);
    try {
      const detail = await firstValueFrom(this.service.getById(id));
      this.suite.set(detail ?? null);
    } catch (err) {
      console.error('Failed to load test suite:', err);
      this.toast.error('Failed to load test suite');
    } finally {
      this.isLoading.set(false);
    }
  }

  // ── Navigation ────────────────────────────────────────────────
  goBack() {
    this.router.navigate(['/test-suites']);
  }

  goToTestPlan() {
    const planId = this.suite()?.test_plan?.id;
    if (planId) {
      this.router.navigate(['/test-plans', planId]);
    }
  }

  openTestCase(tcId: string) {
    this.router.navigate(['/test-cases', tcId]);
  }

  // ── UI helpers ────────────────────────────────────────────────
  toggleCase(id: string) {
    this.expandedCase.set(this.expandedCase() === id ? null : id);
  }

  isCaseExpanded(id: string): boolean {
    return this.expandedCase() === id;
  }

  getSuiteTypeConfig(type?: string | null) {
    return type ? (SUITE_TYPE_CONFIG[type] ?? null) : null;
  }

  getStatusConfig(status: string) {
    return SUITE_STATUS_CONFIG[status] ?? { label: status, color: '#6b7280', bg: '#f3f4f6' };
  }

  getPriorityConfig(prio?: string | null) {
    return prio ? (PRIORITY_CONFIG[prio] ?? null) : null;
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

  getRiskLevelColor(level?: string | null): string {
    const map: Record<string, string> = {
      critical: '#dc2626', high: '#ea580c', medium: '#ca8a04', low: '#16a34a'
    };
    return level ? (map[level] ?? '#6b7280') : '#6b7280';
  }

  getRiskLevelBg(level?: string | null): string {
    const map: Record<string, string> = {
      critical: '#fee2e2', high: '#ffedd5', medium: '#fef9c3', low: '#dcfce7'
    };
    return level ? (map[level] ?? '#f3f4f6') : '#f3f4f6';
  }

  getDependencyEdgeColor(type: string): string {
    const map: Record<string, string> = {
      requires: '#6366f1', blocks: '#ef4444', related: '#6b7280'
    };
    return map[type] ?? '#6b7280';
  }

  getDependencyEdgeLabel(type: string): string {
    const map: Record<string, string> = {
      requires: 'Requires', blocks: 'Blocks', related: 'Related'
    };
    return map[type] ?? type;
  }

  formatDate(d?: string | null): string {
    if (!d) return '—';
    try {
      return new Date(d).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
    } catch {
      return '—';
    }
  }

  gherkinLines(source?: string | null): { type: string; text: string }[] {
    if (!source) return [];
    return source.split('\n').map(line => {
      const t = line.trim();
      if (t.startsWith('@'))              return { type: 'tag', text: line };
      if (t.startsWith('Feature:'))       return { type: 'feature', text: line };
      if (t.startsWith('Scenario'))       return { type: 'scenario', text: line };
      if (t.startsWith('Given'))          return { type: 'step', text: line };
      if (t.startsWith('When'))           return { type: 'step', text: line };
      if (t.startsWith('Then'))           return { type: 'step', text: line };
      if (t.startsWith('And'))            return { type: 'step', text: line };
      if (t.startsWith('But'))            return { type: 'step', text: line };
      if (t.startsWith('|'))              return { type: 'table', text: line };
      if (t.startsWith('#'))              return { type: 'comment', text: line };
      return { type: 'other', text: line };
    });
  }

  priorityKeys(byPriority: Record<string, number>): string[] {
    const order = ['critical', 'high', 'medium', 'low'];
    return order.filter(k => byPriority[k]);
  }

  typeKeys(byType: Record<string, number>): string[] {
    return Object.keys(byType);
  }

  testDataEntries(data: Record<string, unknown>): { key: string; value: string }[] {
    if (!data) return [];
    return Object.entries(data).map(([k, v]) => ({ key: k, value: String(v) }));
  }

  // ── Lifecycle helpers ─────────────────────────────────────────
  getLifecycle() {
    return this.suite()?.lifecycle ?? null;
  }

  getRisks() {
    return this.suite()?.risks ?? [];
  }

  getRiskCount(): number {
    return this.suite()?.risks?.length ?? 0;
  }

  getMatrix() {
    return this.suite()?.traceability_matrix ?? null;
  }

  getGraph() {
    return this.suite()?.dependency_graph ?? null;
  }

  getCoverage() {
    return this.suite()?.coverage ?? null;
  }

  getTestCases() {
    return this.suite()?.test_cases ?? [];
  }

  getActiveTestCases() {
    return this.getTestCases().filter(tc => tc.is_active);
  }

  getAllSuitesOrder() {
    return this.suite()?.all_suites_order ?? [];
  }

  getPriorityReasoning() {
    return this.suite()?.priority_reasoning ?? null;
  }

  // ── Graph helpers ─────────────────────────────────────────────
  findNode(nodes: DependencyNode[], id: string): DependencyNode | undefined {
    return nodes.find(n => n.id === id);
  }

  hasEdge(edges: DependencyEdge[], nodeId: string): boolean {
    return edges.some(e => e.source_id === nodeId || e.target_id === nodeId);
  }

  getNodeEdges(edges: DependencyEdge[], nodeId: string): DependencyEdge[] {
    return edges.filter(e => e.source_id === nodeId || e.target_id === nodeId);
  }

  getExecutionPosition(code: string): number {
    const order = this.suite()?.dependency_graph?.execution_order ?? [];
    return order.indexOf(code) + 1;
  }

  // ── Traceability helpers ──────────────────────────────────────
  getCoveredStoriesCount(): number {
    const matrix = this.getMatrix();
    if (!matrix) return 0;
    return matrix.rows.filter(r => r.covered_cases > 0).length;
  }

  getUncoveredStoriesCount(): number {
    const matrix = this.getMatrix();
    if (!matrix) return 0;
    return matrix.rows.filter(r => r.covered_cases === 0).length;
  }
}