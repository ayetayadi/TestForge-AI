import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';

import { TestSuiteService } from '../../services/test-suite.service';
import { ToastService } from '../../services/toast.service';

import {
  TestSuiteDetail,
  EmbeddedTestCase,
  DependencyNode,
  DependencyEdge,
  SUITE_TYPE_CONFIG,
  SUITE_STATUS_CONFIG,
  PRIORITY_CONFIG,
  MITIGATION_STATUS_CONFIG,
  RiskCoverage,
  UsAcCoverage,
} from '../../models/test-suite.model';

type DetailTab = 'overview' | 'cases' | 'traceability' | 'graph';

// ── Graph layout interfaces ──────────────────────────────────────────────────

interface GraphNodeLayout {
  id: string;
  tc_code: string;
  title: string;
  priority: string | null;
  test_type: string | null;
  x: number;
  y: number;
  exec_pos: number;
}

interface GraphEdgeLayout {
  path: string;
  label_x: number;
  label_y: number;
  source_code: string;
  target_code: string;
  dependency_type: string;
  color: string;
}

interface LayerBand {
  y: number;
  height: number;
  label: string;
  count: number;
  fill: string;
  text_color: string;
}

interface GraphLayoutData {
  nodes: GraphNodeLayout[];
  edges: GraphEdgeLayout[];
  svg_width: number;
  svg_height: number;
  bands: LayerBand[];
}

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
  readonly MITIGATION_STATUS_CONFIG = MITIGATION_STATUS_CONFIG;  // 🆕

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

  goToUserStory(usId: string) {
    this.router.navigate(['/user-stories', usId]);  // 🆕
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

  // ── 🆕 RISK COVERAGE HELPERS ──────────────────────────────────

  getRiskCoverage(): RiskCoverage | null {
    return this.suite()?.risk_coverage ?? null;
  }

  getRiskCoverageColor(pct: number): string {
    if (pct >= 100) return '#10b981';  // Vert - full
    if (pct >= 80) return '#f59e0b';   // Orange - partial
    return '#ef4444';                   // Rouge - low
  }

  getRiskCoverageLabel(pct: number): string {
    if (pct >= 100) return 'Fully Mitigated';
    if (pct >= 80) return 'Partially Mitigated';
    return 'Not Mitigated';
  }

  getMitigationConfig(status: string) {
    return MITIGATION_STATUS_CONFIG[status] ?? { label: status, color: '#6b7280', bg: '#f3f4f6' };
  }

  // ── 🆕 AC COVERAGE PER US HELPERS ─────────────────────────────

  getUsAcCoverages(): UsAcCoverage[] {
    return this.suite()?.us_ac_coverages ?? [];
  }

  getUsWithTests(): UsAcCoverage[] {
    return this.getUsAcCoverages().filter(us => us.has_tests);
  }

  getUsWithoutTests(): UsAcCoverage[] {
    return this.getUsAcCoverages().filter(us => !us.has_tests);
  }

  getTotalAcCovered(): number {
    return this.getUsAcCoverages().reduce((sum, us) => sum + us.covered_ac, 0);
  }

  getTotalAc(): number {
    return this.getUsAcCoverages().reduce((sum, us) => sum + us.total_ac, 0);
  }

  getAverageAcCoverage(): number {
    const usWithTests = this.getUsWithTests();
    if (usWithTests.length === 0) return 0;
    const total = usWithTests.reduce((sum, us) => sum + us.ac_coverage_pct, 0);
    return Math.round(total / usWithTests.length);
  }

  getAcCoverageColor(pct: number): string {
    if (pct >= 100) return '#10b981';
    if (pct >= 80) return '#f59e0b';
    if (pct > 0) return '#ef4444';
    return '#9ca3af';  // Gris pour 0%
  }

  getAcCoverageLabel(us: UsAcCoverage): string {
    if (!us.has_tests) return 'No tests';
    if (us.ac_coverage_pct >= 100) return 'Complete';
    if (us.ac_coverage_pct >= 80) return 'Partial';
    return 'Low';
  }

  // ── RISK LEVEL HELPERS ────────────────────────────────────────

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

  getTestCases() {
    return this.suite()?.test_cases ?? [];
  }

  getActiveTestCases() {
    return this.getTestCases().filter(tc => tc.is_active);
  }

  getAllSuitesOrder() {
    return this.suite()?.all_suites_order ?? [];
  }

  // ── Execution Strategy (replaces Priority Reasoning) ─────────
  private readonly _FLOW_ORDER = [
    'authentication', 'dashboard', 'crud', 'search',
    'reporting', 'settings', 'notifications', 'other',
  ];
  private readonly _FLOW_LABELS: Record<string, string> = {
    authentication: 'Authentication', dashboard: 'Dashboard', crud: 'CRUD',
    search: 'Search & Filter', reporting: 'Reporting & Logs', settings: 'Settings',
    notifications: 'Notifications', other: 'Other',
  };
  private readonly _FLOW_BG: Record<string, string> = {
    authentication: '#eff6ff', dashboard: '#f5f3ff', crud: '#f0fdf4',
    search: '#fff7ed', reporting: '#fffbeb', settings: '#f8fafc',
    notifications: '#fdf4ff', other: '#f9fafb',
  };
  private readonly _FLOW_TEXT: Record<string, string> = {
    authentication: '#1d4ed8', dashboard: '#7c3aed', crud: '#15803d',
    search: '#c2410c', reporting: '#b45309', settings: '#475569',
    notifications: '#9333ea', other: '#6b7280',
  };
  private readonly _FLOW_KEYWORDS: Record<string, string[]> = {
    authentication: ['auth', 'login', 'logout', 'register', 'signup', 'password', 'credential', 'session', 'token', 'sso', '2fa'],
    dashboard:      ['dashboard', 'home', 'overview', 'landing', 'summary', 'welcome'],
    crud:           ['create', 'update', 'delete', 'edit', 'add', 'remove', 'save', 'crud', 'form', 'submit'],
    search:         ['search', 'filter', 'sort', 'query', 'find', 'browse'],
    reporting:      ['report', 'export', 'log', 'audit', 'history', 'analytics', 'metrics'],
    settings:       ['setting', 'config', 'preference', 'profile', 'account', 'permission', 'role'],
    notifications:  ['notification', 'alert', 'email', 'message', 'push', 'reminder'],
  };

  private _detectFlowForTc(tc: EmbeddedTestCase): string {
    const text = `${tc.title ?? ''} ${(tc.tags ?? []).join(' ')}`.toLowerCase();
    for (const [flow, kws] of Object.entries(this._FLOW_KEYWORDS)) {
      if (kws.some(kw => text.includes(kw))) return flow;
    }
    return 'other';
  }

  getBusinessFlowGroups(): { flow: string; label: string; count: number; by_risk: Record<string, number>; bg_color: string; text_color: string }[] {
    const tcs = this.getTestCases();
    const groupMap: Record<string, { count: number; by_risk: Record<string, number> }> = {};
    for (const tc of tcs) {
      const flow = this._detectFlowForTc(tc);
      if (!groupMap[flow]) groupMap[flow] = { count: 0, by_risk: {} };
      groupMap[flow].count++;
      const risk = tc.priority ?? 'low';
      groupMap[flow].by_risk[risk] = (groupMap[flow].by_risk[risk] ?? 0) + 1;
    }
    return this._FLOW_ORDER
      .filter(f => groupMap[f])
      .map(f => ({
        flow: f,
        label: this._FLOW_LABELS[f] ?? f,
        count: groupMap[f].count,
        by_risk: groupMap[f].by_risk,
        bg_color: this._FLOW_BG[f] ?? '#f9fafb',
        text_color: this._FLOW_TEXT[f] ?? '#6b7280',
      }));
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

  /** Returns active test cases to use as matrix columns */
  getMatrixTestCaseHeaders(): EmbeddedTestCase[] {
    return this.getTestCases().filter(tc => tc.is_active);
  }

  /** True if tc_code appears in the covered_by array of an AC row */
  isAcCoveredByTc(coveredBy: string[], tcCode: string): boolean {
    return coveredBy.includes(tcCode);
  }

  /** Number of risks associated with a test case */
  getTcRiskCount(tc: EmbeddedTestCase): number {
    return tc.risk_ids?.length ?? 0;
  }
// test-suite-detail.component.ts

buildGraphLayout(): GraphLayoutData | null {
  const graph = this.getGraph();
  if (!graph || graph.nodes.length === 0) return null;

  const NODE_W  = 160;
  const NODE_H  = 60;
  const H_GAP   = 36;
  const V_GAP   = 80;
  const PAD_X   = 16;
  const PAD_Y   = 24;
  const LABEL_W = 100;
  const ARC_H   = 28;
  const ARROW   = 8;

  // ── 🔥 Utiliser l'ordre LLM du backend (via les nœuds) ──
  // Extraire l'ordre des flux depuis les nœuds eux-mêmes
  const flowOrderFromNodes: string[] = [];
  const seenFlows = new Set<string>();
  for (const node of graph.nodes) {
    const flow = node.business_flow || 'other';
    if (!seenFlows.has(flow)) {
      seenFlows.add(flow);
      flowOrderFromNodes.push(flow);
    }
  }

  // Si le backend a fourni un ordre (via flow_rank), on l'utilise
  // Sinon, on utilise l'ordre d'apparition dans les nœuds
  const FLOW_ORDER = flowOrderFromNodes.length > 0 
    ? flowOrderFromNodes 
    : ['authentication', 'dashboard', 'crud', 'search', 'reporting', 'settings', 'notifications', 'other'];

  const FLOW_LABELS: Record<string, string> = {
    authentication: 'Auth',
    dashboard:      'Dashboard',
    crud:           'CRUD',
    search:         'Search',
    reporting:      'Reporting',
    settings:       'Settings',
    notifications:  'Notifications',
    error_handling: 'Errors',
    monitoring:     'Monitor',
    api:            'API',
    testing:        'Testing',
    other:          'Other',
  };

  const FLOW_BAND_FILL: Record<string, string> = {
    authentication: '#eff6ff', dashboard:     '#f5f3ff',
    crud:           '#f0fdf4', search:        '#fff7ed',
    reporting:      '#fffbeb', settings:      '#f8fafc',
    notifications:  '#fdf4ff', error_handling: '#fef2f2',
    monitoring:     '#ecfeff', api:            '#f0fdf4',
    testing:        '#f5f3ff', other:         '#f9fafb',
  };

  const FLOW_BAND_TEXT: Record<string, string> = {
    authentication: '#1d4ed8', dashboard:     '#7c3aed',
    crud:           '#15803d', search:        '#c2410c',
    reporting:      '#b45309', settings:      '#475569',
    notifications:  '#9333ea', error_handling: '#dc2626',
    monitoring:     '#0891b2', api:            '#059669',
    testing:        '#7c3aed', other:         '#6b7280',
  };

  // ── Risk level priority order within a lane ──
  const RISK_RANK: Record<string, number> = {
    critical: 0, high: 1, medium: 2, low: 3,
  };

  const EDGE_COLORS: Record<string, string> = {
    requires: '#6366f1', blocks: '#ef4444', related: '#9ca3af',
  };

  // ── 🔥 Détection du flux : utiliser le champ business_flow du backend ──
  const detectFlow = (node: DependencyNode): string => {
    // Priorité 1 : Champ business_flow fourni par le backend (classification LLM)
    if (node.business_flow && node.business_flow !== 'other') {
      return node.business_flow;
    }
    
    // Priorité 2 : Vérifier si c'est vraiment "other" du LLM ou non classifié
    if (node.business_flow === 'other') {
      return 'other';
    }
    
    // Fallback : détection par mots-clés (si le backend n'a pas classifié)
    const FLOW_KEYWORDS: Record<string, string[]> = {
      authentication: ['auth', 'login', 'logout', 'register', 'signup', 'password', 'credential', 'session', 'token', 'sso', '2fa', 'mfa'],
      dashboard:      ['dashboard', 'home', 'overview', 'landing', 'summary', 'welcome', 'portal'],
      crud:           ['create', 'update', 'delete', 'edit', 'add', 'remove', 'save', 'crud', 'form', 'submit'],
      search:         ['search', 'filter', 'sort', 'query', 'find', 'browse', 'lookup'],
      reporting:      ['report', 'export', 'log', 'audit', 'history', 'analytics', 'metrics'],
      settings:       ['setting', 'config', 'preference', 'profile', 'account', 'permission', 'role'],
      notifications:  ['notification', 'alert', 'email', 'message', 'push', 'reminder'],
      error_handling: ['error', 'invalid', 'fail', 'reject', 'wrong', 'validation'],
      monitoring:     ['monitor', 'health', 'alert', 'track', 'activity', 'logging', 'performance'],
      api:            ['api', 'endpoint', 'swagger', 'documentation', 'rest', 'curl', 'integration'],
      testing:        ['test', 'automated', 'coverage', 'ci/cd', 'jest', 'playwright', 'pipeline'],
    };
    
    const text = (node.title ?? '').toLowerCase();
    for (const [flow, kws] of Object.entries(FLOW_KEYWORDS)) {
      if (kws.some(kw => text.includes(kw))) return flow;
    }
    return 'other';
  };

  // ── 1. Grouper les nœuds par flux ──
  const laneMap: Record<string, DependencyNode[]> = {};
  for (const node of graph.nodes) {
    const flow = detectFlow(node);
    laneMap[flow] = laneMap[flow] ?? [];
    laneMap[flow].push(node);
  }

  // Trier dans chaque lane par risque (Critical d'abord)
  for (const flow of FLOW_ORDER) {
    if (laneMap[flow]) {
      laneMap[flow].sort((a, b) => 
        (RISK_RANK[a.priority ?? 'low'] ?? 3) - (RISK_RANK[b.priority ?? 'low'] ?? 3)
      );
    }
  }

  // ── 2. Filtrer les lanes actives ──
  // 🔥 Utiliser l'ordre des flux du plan (FLOW_ORDER) mais seulement ceux qui ont des nœuds
  const activeLanes = FLOW_ORDER.filter(f => (laneMap[f]?.length ?? 0) > 0);
  
  // Ajouter les flux qui ne sont pas dans FLOW_ORDER mais qui ont des nœuds
  for (const flow of Object.keys(laneMap)) {
    if (!activeLanes.includes(flow)) {
      activeLanes.push(flow);
    }
  }

  const posById: Record<string, { x: number; y: number }> = {};
  const posNodes: GraphNodeLayout[] = [];
  const bands: LayerBand[] = [];

  // 🔥 Utiliser l'execution_order du backend
  const execOrder = graph.execution_order || [];

  // ── 3. Assigner les positions ──
  activeLanes.forEach((flow, li) => {
    const rowY = PAD_Y + li * (NODE_H + V_GAP);

    bands.push({
      y: rowY - V_GAP * 0.25,
      height: NODE_H + V_GAP * 0.5,
      label: FLOW_LABELS[flow] ?? flow.charAt(0).toUpperCase() + flow.slice(1),
      count: laneMap[flow].length,
      fill: FLOW_BAND_FILL[flow] ?? '#f9fafb',
      text_color: FLOW_BAND_TEXT[flow] ?? '#6b7280',
    });

    laneMap[flow].forEach((node, ni) => {
      const x = PAD_X + LABEL_W + ni * (NODE_W + H_GAP);
      const y = rowY;
      posById[node.id] = { x, y };

      // Position dans l'ordre d'exécution
      const execPos = execOrder.indexOf(node.tc_code) + 1;

      posNodes.push({
        id: node.id,
        tc_code: node.tc_code,
        title: (node.title ?? '').length > 24 
          ? (node.title ?? '').slice(0, 24) + '…' 
          : (node.title ?? ''),
        priority: node.priority ?? null,
        test_type: node.test_type ?? null,
        x,
        y,
        exec_pos: execPos > 0 ? execPos : li + 1,
      });
    });
  });

  // ── 4. Créer les arêtes ──
  const posEdges: GraphEdgeLayout[] = [];

  for (const edge of graph.edges) {
    const src = posById[edge.source_id];
    const tgt = posById[edge.target_id];
    if (!src || !tgt) continue;

    const srcNode = graph.nodes.find(n => n.id === edge.source_id);
    const tgtNode = graph.nodes.find(n => n.id === edge.target_id);
    const srcFlow = srcNode ? detectFlow(srcNode) : 'other';
    const tgtFlow = tgtNode ? detectFlow(tgtNode) : 'other';

    let path: string;
    let lx: number;
    let ly: number;

    if (srcFlow === tgtFlow) {
      // Même lane → flèche horizontale
      const x1 = src.x + NODE_W;
      const y1 = src.y + NODE_H / 2;
      const x2 = tgt.x - ARROW;
      const y2 = tgt.y + NODE_H / 2;
      path = `M ${x1} ${y1} L ${x2} ${y2}`;
      lx = (x1 + x2) / 2;
      ly = y1 - 10;
    } else {
      // Cross-lane → courbe de Bézier
      const x1 = src.x + NODE_W / 2;
      const y1 = src.y + NODE_H;
      const x2 = tgt.x + NODE_W / 2;
      const y2 = tgt.y - ARROW;
      const cp1y = y1 + (y2 - y1) * 0.4;
      const cp2y = y1 + (y2 - y1) * 0.6;
      path = `M ${x1} ${y1} C ${x1} ${cp1y}, ${x2} ${cp2y}, ${x2} ${y2}`;
      lx = (x1 + x2) / 2;
      ly = (y1 + y2) / 2;
    }

    posEdges.push({
      path,
      label_x: lx,
      label_y: ly,
      source_code: edge.source,
      target_code: edge.target,
      dependency_type: edge.dependency_type || 'requires',
      color: EDGE_COLORS[edge.dependency_type] ?? '#9ca3af',
    });
  }

  // ── 5. Taille du canvas ──
  const maxPerLane = Math.max(...activeLanes.map(f => laneMap[f].length), 1);
  const svgW = PAD_X * 2 + LABEL_W + maxPerLane * (NODE_W + H_GAP) - H_GAP;
  const svgH = PAD_Y * 2 + activeLanes.length * (NODE_H + V_GAP) - V_GAP;

  console.log(
    `[GRAPH] ${posNodes.length} nodes, ${posEdges.length} edges, ${activeLanes.length} lanes`,
    'flows:', activeLanes,
    'order:', execOrder.slice(0, 5)
  );

  return {
    nodes: posNodes,
    edges: posEdges,
    svg_width: Math.max(svgW, 420),
    svg_height: Math.max(svgH, 180),
    bands,
  };
}
  // ── Node/edge colour helpers (used in SVG bindings) ───────────

  getNodeFill(priority: string | null): string {
    const m: Record<string, string> = {
      critical: '#fef2f2', high: '#fff7ed', medium: '#fefce8', low: '#f0fdf4',
    };
    return m[priority ?? ''] ?? '#f9fafb';
  }

  getNodeStroke(priority: string | null): string {
    const m: Record<string, string> = {
      critical: '#ef4444', high: '#f97316', medium: '#eab308', low: '#22c55e',
    };
    return m[priority ?? ''] ?? '#e5e7eb';
  }
}