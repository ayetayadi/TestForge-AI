import { Component, OnInit, OnDestroy, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, ActivatedRoute } from '@angular/router';
import {
  RiskService,
  ProgressiveAnalysisStrategy,
  RiskAnalysisValidator,
  ProjectAnalysisRequest,
} from '../../services/risk.service';
import { ProjectsService } from '../../services/projects.service';
import { StoriesService } from '../../services/stories.service';
import { ToastService } from '../../services/toast.service';
import {
  Risk,
  RiskLevel,
  RiskSummary,
  RiskMatrixCell,
  RISK_LEVEL_CONFIG,
  PROB_BANDS,
  IMPACT_LEVELS,
  classifyLevel,
  mapProbToRow,
} from '../../models/risk.model';
import { Project, UserStory } from '../../models/user_story.model';
import { SearchBarComponent } from '../../components/search-bar/search-bar.component';
import { PaginationComponent } from '../../components/pagination/pagination.component';

type FilterTab = 'all' | RiskLevel;

@Component({
  selector: 'app-risk-analysis',
  standalone: true,
  imports: [CommonModule, FormsModule, SearchBarComponent, PaginationComponent],
  templateUrl: './risk-analysis.component.html',
  styleUrl: './risk-analysis.component.scss',
})
export class RiskAnalysisComponent implements OnInit, OnDestroy {
  private riskService      = inject(RiskService);
  private projectsService  = inject(ProjectsService);
  private storiesService   = inject(StoriesService);
  private router           = inject(Router);
  private route            = inject(ActivatedRoute);
  private toast            = inject(ToastService);
  private analysisStrategy = new ProgressiveAnalysisStrategy(this.riskService);

  // ── Data ─────────────────────────────────────────────────
  projects   = signal<Project[]>([]);
  allRisks   = signal<Risk[]>([]);
  allStories = signal<UserStory[]>([]);
  analysisLimit = signal<string>('100'); 

  // ── Selection ─────────────────────────────────────────────
  selectedProjectId     = signal<string>('');
  selectedSprintFilter  = signal<string>('');
  selectedEpicFilter    = signal<string>('');
  hoveredCell           = signal<{ row: number; col: number } | null>(null);

  // ── Analysis filters ─────────────────────────────────────
  showFilterPanel = signal(false);
  showMatrix      = signal(true);
  analysisFilters = signal<Partial<ProjectAnalysisRequest>>({
    limit: 100,
    min_story_points: undefined,
    force_reanalyze: false,
  });
  availableEpics   = signal<string[]>([]);
  availableSprints = signal<string[]>([]);

  // ── UI state ──────────────────────────────────────────────
  loadingRisks    = signal(false);
  analyzing       = signal(false);
  analyzeProgress = signal<{ done: number; total: number; currentBatch?: string }>({ done: 0, total: 0 });
  activeFilter    = signal<FilterTab>('all');

  // ── Search & Pagination ───────────────────────────────────
  searchQuery = signal('');
  currentPage = signal(1);
  pageSize    = signal(12);


  // New variables for pending analysis
  pendingStories = signal<number>(0);
  totalStories = signal<number>(0);
  analyzedStories = signal<number>(0);
  pendingBreakdown = signal<Record<string, number>>({});
  showRemainingBanner = signal<boolean>(false);

  // ── SSE ───────────────────────────────────────────────────
  private sseConnections = new Map<string, EventSource>();
  private currentJobIds: string[] = [];

  // ── Exposed constants ─────────────────────────────────────
  readonly PROB_BANDS       = PROB_BANDS;
  readonly IMPACT_LEVELS    = IMPACT_LEVELS;
  readonly LEVELS: FilterTab[] = ['all', 'critical', 'high', 'medium', 'low'];
  readonly PRIORITY_OPTIONS = ['Highest', 'High', 'Medium', 'Low'];

  // ── Computed ──────────────────────────────────────────────

  /** Risks filtered by selected project (or all if none selected) */
  risks = computed(() => {
    const pid = this.selectedProjectId();
    if (!pid) return this.allRisks();
    return this.allRisks().filter(r => r.project_id === pid);
  });

  /** Map user_story_id → UserStory for fast lookups */
  storyMap = computed((): Map<string, UserStory> => {
    const m = new Map<string, UserStory>();
    for (const s of this.allStories()) m.set(s.id, s);
    return m;
  });

  /** Unique sprints available among currently visible risks */
  viewSprints = computed((): string[] => {
    const map = this.storyMap();
    const set = new Set<string>();
    for (const r of this.risks()) {
      if (r.user_story_id) {
        const sprint = map.get(r.user_story_id)?.sprint;
        if (sprint) set.add(sprint);
      }
    }
    return Array.from(set).sort();
  });


private loadProjectMetadata(projectId: string): void {
  if (!projectId) {
    this.availableEpics.set([]);
    this.availableSprints.set([]);
    return;
  }

  const projectStories = this.allStories().filter(s => s.project_id === projectId);
  
  const epicsSet = new Set<string>();
  const sprintsSet = new Set<string>();
  
  for (const story of projectStories) {
    const epic = story.epic_name ?? story.epic_key;
    if (epic) epicsSet.add(epic);
    if (story.sprint) sprintsSet.add(story.sprint);
  }
  
  this.availableEpics.set(Array.from(epicsSet).sort());
  this.availableSprints.set(Array.from(sprintsSet).sort());
}


analyzeEverything(): void {
  const projectId = this.selectedProjectId();
  if (!projectId) return;

  this.analyzing.set(true);
  this.analyzeProgress.set({ done: 0, total: 0 });

  this.riskService.analyzeProjectWithFilters({
    project_id: projectId,
    force_reanalyze: false
  }).subscribe({
    next: (response) => {
      if (response.submitted === 0) {
        this.analyzing.set(false);
        this.toast.info('Nothing to analyze', response.message || 'All stories are already analyzed.');
        return;
      }
      this.analyzeProgress.set({ done: 0, total: response.job_ids.length });
      this.toast.info('Analysis started', `Analyzing ${response.submitted} stories`);
      this.listenToJobs(response.job_ids);
    },
    error: (err) => {
      this.analyzing.set(false);
      this.toast.error('Error', err.message);
    }
  });
}


// Calculate progress percentage
getProgressPercentage(): number {
  const total = this.analyzeProgress().total;
  const done = this.analyzeProgress().done;
  if (total === 0) return 0;
  return Math.round((done / total) * 100);
}

// Calculate remaining stories count
getRemainingCount(): number {
  const total = this.analyzeProgress().total;
  const done = this.analyzeProgress().done;
  return total - done;
}

// Calculate estimated time remaining (minutes)
getEstimatedTimeRemaining(): string | null {
  const remaining = this.getRemainingCount();
  if (remaining === 0) return null;
  
  // ~8 seconds per story with rate limiting
  const minutes = Math.ceil((remaining * 8) / 60);
  
  if (minutes < 1) return "<1";
  return `${minutes}`;
}

  /** Unique epics available among currently visible risks */
  viewEpics = computed((): string[] => {
    const map = this.storyMap();
    const set = new Set<string>();
    for (const r of this.risks()) {
      if (r.user_story_id) {
        const s = map.get(r.user_story_id);
        const key = s?.epic_name ?? s?.epic_key;
        if (key) set.add(key);
      }
    }
    return Array.from(set).sort();
  });

  /** Risks after sprint + epic view filters */
  sprintEpicFilteredRisks = computed((): Risk[] => {
    const sprint = this.selectedSprintFilter();
    const epic   = this.selectedEpicFilter();
    const map    = this.storyMap();
    if (!sprint && !epic) return this.risks();
    return this.risks().filter(r => {
      if (!r.user_story_id) return false;
      const s = map.get(r.user_story_id);
      if (!s) return false;
      if (sprint && s.sprint !== sprint) return false;
      if (epic) {
        const key = s.epic_name ?? s.epic_key;
        if (key !== epic) return false;
      }
      return true;
    });
  });

  /** Summary computed client-side from current risks */
  summary = computed((): RiskSummary | null => {
    const r = this.risks();
    if (!r.length) return null;
    const by_level = { critical: 0, high: 0, medium: 0, low: 0 };
    let total_score = 0, accepted = 0, rejected = 0;
    for (const risk of r) {
      by_level[risk.level as RiskLevel] = (by_level[risk.level as RiskLevel] ?? 0) + 1;
      total_score += risk.risk_score;
      if (risk.is_accepted === true) accepted++;
      else if (risk.is_accepted === false) rejected++;
    }
    return {
      total: r.length,
      by_level,
      avg_score: Math.round(total_score / r.length * 100) / 100,
      accepted_count: accepted,
      rejected_count: rejected,
      pending_count: r.length - accepted - rejected,
    };
  });

  searchFilteredRisks = computed(() => {
    const q = this.searchQuery().toLowerCase().trim();
    const f = this.activeFilter();
    let list = f === 'all'
      ? this.sprintEpicFilteredRisks()
      : this.sprintEpicFilteredRisks().filter(r => r.level === f);
    if (!q) return list;
    return list.filter(r =>
      r.description.toLowerCase().includes(q) ||
      (r.user_story_key  ?? '').toLowerCase().includes(q) ||
      (r.user_story_title ?? '').toLowerCase().includes(q) ||
      r.level.includes(q),
    );
  });

  paginatedRisks = computed(() => {
    const start = (this.currentPage() - 1) * this.pageSize();
    return this.searchFilteredRisks().slice(start, start + this.pageSize());
  });

  matrixCells = computed((): RiskMatrixCell[][] =>
    PROB_BANDS.map((band, row) =>
      IMPACT_LEVELS.map((impact, col) => {
        const bgScore   = Math.round(band.pMid * impact.value * 100) / 100;
        const level     = classifyLevel(bgScore);
        const cellRisks = this.risks().filter(
          r => mapProbToRow(r.probability) === row && r.impact - 1 === col,
        );
        return { row, col, level, bgScore, risks: cellRisks };
      }),
    )
  );

  totalByLevel = computed(() => {
    const s = this.summary();
    return {
      critical: s?.by_level?.critical ?? 0,
      high:     s?.by_level?.high     ?? 0,
      medium:   s?.by_level?.medium   ?? 0,
      low:      s?.by_level?.low      ?? 0,
    };
  });

  acceptanceRate = computed(() => {
    const s = this.summary();
    if (!s || s.total === 0) return 0;
    return Math.round(((s.accepted_count ?? 0) + (s.rejected_count ?? 0)) / s.total * 100);
  });

  hasActiveFilters = computed(() => {
    const f = this.analysisFilters();
    return !!(f.epic_keys?.length || f.sprint_ids?.length || f.jira_priorities?.length || f.min_story_points);
  });

  // ── Lifecycle ─────────────────────────────────────────────
  ngOnInit(): void {
    this.loadProjects();
    this.loadAllRisks();
    this.loadAllStories();
    this.setAnalysisLimit('100');
    const projectId = this.route.snapshot.queryParamMap.get('project');
    if (projectId) {
      this.selectedProjectId.set(projectId);
      this.checkPendingStories();
    }
  }

  ngOnDestroy(): void {
    this.clearPolling();
  }

  // ── Loaders ───────────────────────────────────────────────
  loadProjects(): void {
    this.projectsService.getProjects().subscribe({
      next: p => this.projects.set(p),
    });
  }

  loadAllRisks(): void {
    this.loadingRisks.set(true);
    this.riskService.getAllRisks().subscribe({
      next: risks => { this.allRisks.set(risks); this.loadingRisks.set(false); },
      error: ()    => { this.loadingRisks.set(false); this.toast.error('Failed to load risks'); },
    });
  }

loadAllStories(): void {
  this.storiesService.getAllStories().subscribe({
    next: stories => { 
      this.allStories.set(stories);
      this.loadProjectMetadata(this.selectedProjectId());
    },
    error: (err) => {
      console.error('Failed to load stories:', err);
    }
  });
}

  onProjectChange(projectId: string): void {
    this.selectedProjectId.set(projectId);
    this.selectedSprintFilter.set('');
    this.selectedEpicFilter.set('');
    this.analyzing.set(false);
    this.searchQuery.set('');
    this.currentPage.set(1);
    this.clearPolling();
    this.loadProjectMetadata(projectId); 
    this.checkPendingStories(); 
    this.router.navigate([], { queryParams: { project: projectId || null }, queryParamsHandling: 'merge' });
  }

  onSprintFilterChange(sprint: string): void {
    this.selectedSprintFilter.set(sprint);
    this.currentPage.set(1);
  }

    checkPendingStories(): void {
    const projectId = this.selectedProjectId();
    if (!projectId) {
      this.pendingStories.set(0);
      this.showRemainingBanner.set(false);
      return;
    }
    
    const filters = {
      project_id: projectId,
      epic_keys: this.analysisFilters().epic_keys,
      sprint_ids: this.analysisFilters().sprint_ids,
      jira_priorities: this.analysisFilters().jira_priorities,
      min_story_points: this.analysisFilters().min_story_points,
    };
    
    this.riskService.getPendingCount(filters).subscribe({
      next: (data) => {
        this.totalStories.set(data.total_stories);
        this.analyzedStories.set(data.analyzed_stories);
        this.pendingStories.set(data.pending_stories);
        this.pendingBreakdown.set(data.priority_breakdown);
        this.showRemainingBanner.set(data.has_pending && !this.analyzing());
      },
      error: (err) => console.error('Failed to get pending count:', err)
    });
  }

    // Analyze only remaining stories
  analyzeRemainingStories(): void {
    if (this.pendingStories() === 0) {
      this.toast.info('Nothing to analyze', 'All stories are already analyzed.');
      return;
    }
    
    // Show confirmation with details
    const priorityText = Object.entries(this.pendingBreakdown())
      .map(([prio, count]) => `${prio}: ${count}`)
      .join(', ');
    
    const confirmed = confirm(
      `📊 ${this.pendingStories()} stories remaining to analyze:\n` +
      `${priorityText}\n\n` +
      `Continue with analysis? (Highest priority first)`
    );
    
    if (!confirmed) return;
    
    // Update limit to match pending stories (or keep max 100)
    const limit = Math.min(this.pendingStories(), 100);
    this.updateFilter('limit', limit);
    
    // Start analysis
    this.analyzeProject();
  }

  onEpicFilterChange(epic: string): void {
    this.selectedEpicFilter.set(epic);
    this.currentPage.set(1);
  }

  
setAnalysisLimit(value: string): void {
  this.analysisLimit.set(value);
  
  // Update the analysisFilters limit accordingly
  if (value === 'all') {
    this.updateFilter('limit', undefined);
  } else {
    this.updateFilter('limit', parseInt(value, 10));
  }
}
  // ── Analysis ──────────────────────────────────────────────
async analyzeProject(): Promise<void> {
  const projectId = this.selectedProjectId();
  if (!projectId || this.analyzing()) return;

  const canAnalyze = await RiskAnalysisValidator.canAnalyzeSafely(this.riskService);
  if (!canAnalyze.safe) {
    this.toast.warning('Rate limit warning', canAnalyze.reason ?? 'Use filters to analyze in smaller batches.');
    return;
  }

  this.analyzing.set(true);
  this.analyzeProgress.set({ done: 0, total: 0 });

  // 🔧 NETTOYAGE DES FILTRES
  const filters = this.analysisFilters();
  const limitMode = this.analysisLimit();  
  
  // 🆕 CAS 1: Mode "All stories" (sans limite)
  if (limitMode === 'all') {
    this.riskService.analyzeProjectWithFilters({
      project_id: projectId,
      test_plan_id: filters.test_plan_id,
      epic_keys: filters.epic_keys,
      sprint_ids: filters.sprint_ids,
      jira_priorities: filters.jira_priorities,
      min_story_points: filters.min_story_points,
      force_reanalyze: filters.force_reanalyze,
      limit: undefined
    }).subscribe({
      next: (response) => {
        if (response.submitted === 0) {
          this.analyzing.set(false);
          this.toast.info('Nothing to analyze', response.message || 'All stories are already analyzed.');
          return;
        }
        this.analyzeProgress.set({ done: 0, total: response.submitted });
        this.toast.info('Analysis started', `${response.submitted} stories queued (ALL stories).`);
        this.listenToJobs(response.job_ids);
      },
      error: (err) => {
        console.error('❌ Erreur analyse:', err);
        this.analyzing.set(false);
        this.toast.error('Analysis failed', err.message || 'Could not start analysis');
      },
    });
    return;  // ← IMPORTANT: sortir de la fonction
  }
  
  // 🎯 CAS 2: Mode normal (avec limite) - Ton code existant
  const cleanRequest: any = { project_id: projectId };
  
  // AJOUTER SEULEMENT LES FILTRES QUI ONT DES VALEURS
  if (filters.limit) cleanRequest.limit = filters.limit;
  if (filters.test_plan_id) cleanRequest.test_plan_id = filters.test_plan_id;
  if (filters.min_story_points !== undefined && filters.min_story_points !== null) {
    cleanRequest.min_story_points = filters.min_story_points;
  }
  if (filters.force_reanalyze) cleanRequest.force_reanalyze = filters.force_reanalyze;
  
  // POUR LES TABLEAUX: ENVOYER SEULEMENT S'ILS CONTIENNENT DES ÉLÉMENTS
  if (filters.epic_keys && filters.epic_keys.length > 0) {
    cleanRequest.epic_keys = filters.epic_keys;
  }
  if (filters.sprint_ids && filters.sprint_ids.length > 0) {
    cleanRequest.sprint_ids = filters.sprint_ids;
  }
  if (filters.jira_priorities && filters.jira_priorities.length > 0) {
    cleanRequest.jira_priorities = filters.jira_priorities;
  }

  console.log('🔍 Envoi de la requête propre:', cleanRequest);

  // ENVOYER LA REQUÊTE NETTOYÉE
  this.riskService.analyzeProjectWithFilters(cleanRequest).subscribe({
    next: response => {
      if (response.submitted === 0) {
        this.analyzing.set(false);
        this.toast.info('Nothing to analyze', response.message || 'All stories are already analyzed.');
        return;
      }
      this.analyzeProgress.set({ done: 0, total: response.submitted });
      this.toast.info('Analysis started', `${response.submitted} user stories queued.`);
      this.listenToJobs(response.job_ids);
    },
    error: (err) => {
      console.error('❌ Erreur analyse:', err);
      this.analyzing.set(false);
      this.toast.error('Analysis failed', err.message || 'Could not start analysis');
    },
  });
}

  async analyzeProjectProgressively(): Promise<void> {
    const projectId = this.selectedProjectId();
    if (!projectId) return;
    this.analyzing.set(true);
    this.analyzeProgress.set({ done: 0, total: 0, currentBatch: 'Preparing...' });
    this.toast.info('Progressive analysis started', 'Analyzing by priority...');

    await this.analysisStrategy.analyzeProjectByPriority(
      projectId,
      ['Highest', 'High'],
      (cur, tot, priority) => {
        this.analyzeProgress.set({ done: 0, total: 0, currentBatch: `Priority ${priority} (${cur}/${tot})...` });
      },
    );

    this.refreshDataAfterAnalysis();
  }

  analyzeByPriority(priority: string): void {
    const projectId = this.selectedProjectId();
    if (!projectId) return;
    this.analyzing.set(true);
    this.riskService.analyzeProjectWithFilters({ project_id: projectId, jira_priorities: [priority], limit: 15 }).subscribe({
      next: r => {
        if (r.submitted > 0) {
          this.analyzeProgress.set({ done: 0, total: r.submitted });
          this.toast.info(`Analyzing ${priority}`, `${r.submitted} stories queued.`);
          this.listenToJobs(r.job_ids);
        } else {
          this.analyzing.set(false);
          this.toast.info('Nothing to analyze', `All ${priority} stories are already analyzed.`);
        }
      },
      error: () => { this.analyzing.set(false); this.toast.error('Analysis failed'); },
    });
  }

  getPendingBreakdownKeys(): string[] {
  return Object.keys(this.pendingBreakdown());
}


private pollingInterval: any = null;
private pollingTimeout: any = null;

private listenToJobs(jobIds: string[]): void {
  this.currentJobIds = jobIds;
  let attempts = 0;
  const maxAttempts = 30; // 30 × 2s = 60 secondes max
  const startTime = Date.now();

  // Nettoie tout polling précédent
  this.clearPolling();

  const checkResults = () => {
    attempts++;

    // Timeout après 60 secondes
    if (attempts > maxAttempts) {
      this.clearPolling();
      this.riskService.getAllRisks().subscribe({
        next: (risks) => {
          const newRisks = risks.filter(r => 
            this.currentJobIds.some(jobId => jobId.includes(r.user_story_id || ''))
          ).length;
          this.finishAnalysis(newRisks, this.currentJobIds.length - newRisks);
        },
        error: () => {
          this.finishAnalysis(0, this.currentJobIds.length);
        }
      });
      return;
    }

    // Vérifie les risques
    this.riskService.getAllRisks().subscribe({
      next: (risks) => {
        // Compte combien de user_story_id des jobs actuels ont un risque
        const completedCount = this.currentJobIds.filter(jobId => 
          risks.some(risk => jobId.includes(risk.user_story_id || ''))
        ).length;

        // Met à jour la barre de progression
        this.analyzeProgress.update(p => ({
          ...p,
          done: completedCount,
          total: this.currentJobIds.length,
          currentBatch: `Processing ${completedCount}/${this.currentJobIds.length}...`
        }));

        // Si tous les jobs ont leur risque → terminé
        if (completedCount >= this.currentJobIds.length) {
          this.clearPolling();
          this.finishAnalysis(completedCount, 0);
          return;
        }

        // Continue le polling
        this.pollingInterval = setTimeout(checkResults, 2000);
      },
      error: () => {
        // En cas d'erreur réseau, on continue d'essayer
        this.pollingInterval = setTimeout(checkResults, 2000);
      }
    });
  };

  // Commence après 2 secondes (laisse le temps au backend de traiter)
  this.pollingInterval = setTimeout(checkResults, 2000);
}

private clearPolling(): void {
  if (this.pollingInterval) {
    clearTimeout(this.pollingInterval);
    this.pollingInterval = null;
  }
  if (this.pollingTimeout) {
    clearTimeout(this.pollingTimeout);
    this.pollingTimeout = null;
  }
}

private finishAnalysis(success: number, failed: number): void {
  // Recharger les données MÊME si certains jobs ont échoué
  this.riskService.getAllRisks().subscribe({
    next: (risks) => {
      this.allRisks.set([...risks]);
      
      this.storiesService.getAllStories().subscribe({
        next: (stories) => {
          this.allStories.set([...stories]);
          this.loadProjectMetadata(this.selectedProjectId());
          
          this.analyzing.set(false);
          this.loadingRisks.set(false);
          this.analyzeProgress.set({ done: 0, total: 0, currentBatch: undefined });
          
          this.selectedSprintFilter.set('');
          this.selectedEpicFilter.set('');
          this.searchQuery.set('');
          this.currentPage.set(1);
          this.checkPendingStories();
          this.currentJobIds = [];
          
          // 🔥 Toast ADAPTÉ selon le résultat
          if (failed === 0) {
            this.toast.success('Analysis complete', `${success} jobs analyzed successfully.`);
          } else {
            this.toast.warning(
              'Analysis partially complete', 
              `${success} succeeded, ${failed} failed (rate limit). You can retry.`
            );
          }
        },
        error: (err) => {
          console.error('❌ Error reloading stories:', err);
          this.finalizeAnalysis();
        }
      });
    },
    error: (err) => {
      console.error('❌ Error reloading risks:', err);
      this.loadingRisks.set(false);
      this.finalizeAnalysis();
    }
  });
}

private refreshDataAfterAnalysis(): void {
  const totalJobs = this.currentJobIds.length;
  this.riskService.getAllRisks().subscribe({
    next: (risks) => {
      console.log('✅ Risques rechargés:', risks.length);
      
      // Mettre à jour les risques
      this.allRisks.set([...risks]); 
      
      // Ensuite, recharger les stories
      this.storiesService.getAllStories().subscribe({
        next: (stories) => {
          console.log('✅ Stories rechargées:', stories.length);
          this.allStories.set([...stories]);
          
          // Mettre à jour les métadonnées
          this.loadProjectMetadata(this.selectedProjectId());
          
          // Réinitialiser l'état APRÈS le chargement
          this.analyzing.set(false);
          this.loadingRisks.set(false);
          this.analyzeProgress.set({ done: 0, total: 0, currentBatch: undefined });
          
          // Réinitialiser les filtres de vue
          this.selectedSprintFilter.set('');
          this.selectedEpicFilter.set('');
          this.searchQuery.set('');
          this.currentPage.set(1);
          
          // Vérifier les stories restantes
          this.checkPendingStories();
          
          // Afficher le toast de succès
          this.currentJobIds = [];
          this.toast.success(
              'Analysis complete', 
              `${totalJobs} job${totalJobs > 1 ? 's' : ''} analyzed successfully.`
          );
        },
        error: (err) => {
          console.error('❌ Erreur rechargement stories:', err);
          this.finalizeAnalysis();
        }
      });
    },
    error: (err) => {
      console.error('❌ Erreur rechargement risques:', err);
      this.loadingRisks.set(false)
      this.finalizeAnalysis();
    }
  });
}

private finalizeAnalysis(): void {
  this.analyzing.set(false);
  this.analyzeProgress.set({ done: 0, total: 0, currentBatch: undefined });
  this.loadingRisks.set(false);
}

// Add this helper method
private refreshStoriesAndMetadata(): void {
  this.storiesService.getAllStories().subscribe({
    next: stories => {
      this.allStories.set(stories);
      this.loadProjectMetadata(this.selectedProjectId());
    },
    error: err => console.error('Failed to refresh stories:', err)
  });
}

  private closeSseConnections(): void {
    this.sseConnections.forEach(es => es.close());
    this.sseConnections.clear();
  }

  // ── Filters ───────────────────────────────────────────────
  toggleFilterPanel(): void { this.showFilterPanel.set(!this.showFilterPanel()); }
  toggleMatrix(): void      { this.showMatrix.set(!this.showMatrix()); }

  updateFilter<K extends keyof ProjectAnalysisRequest>(key: K, value: ProjectAnalysisRequest[K]): void {
    this.analysisFilters.update(f => ({ ...f, [key]: value }));
  }

  addFilterValue(key: 'epic_keys' | 'sprint_ids' | 'jira_priorities', value: string): void {
    if (!value) return;
    this.analysisFilters.update(f => {
      const current = f[key] || [];
      return current.includes(value) ? f : { ...f, [key]: [...current, value] };
    });
  }

  removeFilterValue(key: 'epic_keys' | 'sprint_ids' | 'jira_priorities', value: string): void {
    this.analysisFilters.update(f => ({ ...f, [key]: ((f[key] as string[]) ?? []).filter(v => v !== value) }));
  }

  clearFilters(): void {
  const currentLimit = this.analysisLimit();
  
  this.analysisFilters.set({
    limit: currentLimit === 'all' ? undefined : parseInt(currentLimit, 10),
    epic_keys: [],
    sprint_ids: [],
    jira_priorities: [],
    min_story_points: undefined,
    force_reanalyze: false,
  });
  }

  // ── Search & Pagination ───────────────────────────────────
  onSearch(q: string): void { this.searchQuery.set(q); this.currentPage.set(1); }
  onPageChange(page: number): void { this.currentPage.set(page); }
  onPageSizeChange(size: number): void { this.pageSize.set(size); this.currentPage.set(1); }

  // ── Navigation ────────────────────────────────────────────
  openRisk(risk: Risk): void {
    this.router.navigate(['/risk-analysis', risk.id], {
      queryParams: { project: risk.project_id },
    });
  }

  selectCell(cell: RiskMatrixCell): void {
    if (cell.risks.length === 0) return;
    this.openRisk(cell.risks[0]);
  }

  // ── UI helpers ────────────────────────────────────────────
  setFilter(f: FilterTab): void { this.activeFilter.set(f); this.currentPage.set(1); }

  levelLabel(level: FilterTab): string {
    if (level === 'all') return 'All';
    return RISK_LEVEL_CONFIG[level].label;
  }

  levelCount(level: FilterTab): number {
    if (level === 'all') return this.sprintEpicFilteredRisks().length;
    return this.sprintEpicFilteredRisks().filter(r => r.level === level).length;
  }

  projectName(projectId: string): string {
    return this.projects().find(p => p.id === projectId)?.project_name ?? projectId;
  }

  formatScore(score: number): string { return score.toFixed(2); }
  probPercent(p: number): number     { return Math.round(p * 100); }

  acceptanceLabel(val: boolean | null): string {
    if (val === true)  return 'Accepted';
    if (val === false) return 'Rejected';
    return 'Pending';
  }

  usLabel(risk: Risk): string {
    return risk.user_story_key ?? '—';
  }

  getStorySprint(risk: Risk): string | null {
    if (!risk.user_story_id) return null;
    return this.storyMap().get(risk.user_story_id)?.sprint ?? null;
  }

  getStoryEpic(risk: Risk): string | null {
    if (!risk.user_story_id) return null;
    const s = this.storyMap().get(risk.user_story_id);
    return s?.epic_name ?? s?.epic_key ?? null;
  }

  hasViewFilters(): boolean {
    return !!(this.selectedSprintFilter() || this.selectedEpicFilter());
  }

  clearViewFilters(): void {
    this.selectedSprintFilter.set('');
    this.selectedEpicFilter.set('');
    this.currentPage.set(1);
  }

  trackByRiskId(_: number, r: Risk): string { return r.id; }
}
