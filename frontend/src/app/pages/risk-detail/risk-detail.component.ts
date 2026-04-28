import { Component, OnInit, signal, computed, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, ActivatedRoute } from '@angular/router';
import { RiskService } from '../../services/risk.service';
import { StoriesService } from '../../services/stories.service';
import { ToastService } from '../../services/toast.service';
import { Risk, RISK_LEVEL_CONFIG } from '../../models/risk.model';
import { UserStory } from '../../models/user_story.model';

@Component({
  selector: 'app-risk-detail',
  standalone: true,
  imports: [CommonModule, FormsModule],
  templateUrl: './risk-detail.component.html',
  styleUrls: ['./risk-detail.component.scss']
})
export class RiskDetailComponent implements OnInit {
  private riskService = inject(RiskService);
  private storiesService = inject(StoriesService);
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private toast = inject(ToastService);

  // Données
  risk = signal<Risk | null>(null);
  allStories = signal<UserStory[]>([]);
  loading = signal(true);
  notFound = signal(false);
  
  // Édition mitigation
  editingMitigation = signal(false);
  mitigationDraft = '';
  saving = signal(false);
  editingFormula = signal(false);
  probabilityDraft = 0.5;
  impactDraft = 3;
  savingFormula = signal(false);

  // Configuration
  readonly levelConfig = RISK_LEVEL_CONFIG;

  // Computed: Map pour lookup rapide des stories (fallback uniquement)
  storyMap = computed((): Map<string, UserStory> => {
    const map = new Map<string, UserStory>();
    for (const story of this.allStories()) {
      map.set(story.id, story);
    }
    return map;
  });

  // Computed: Liste des steps de mitigation
  mitigationSteps = computed((): string[] => {
    const mitigation = this.risk()?.mitigation;
    if (!mitigation) return [];
    return mitigation.split('\n').filter(step => step.trim().length > 0);
  });

  // Computed: Indique si la source est une version approuvée
  isFromApprovedVersion = computed((): boolean => {
    return this.risk()?.source === 'approved_version';
  });


  computedScoreDraft = computed((): number => {
    return Math.round(this.probabilityDraft * this.impactDraft * 100) / 100;
  });

  computedLevelDraft = computed((): string => {
    const score = this.computedScoreDraft();
    if (score >= 4.0) return 'critical';
    if (score >= 2.5) return 'high';
    if (score >= 1.0) return 'medium';
    return 'low';
  });

  ngOnInit(): void {
    this.loadRisk();
    // Ne charge les stories originales qu'en fallback
    this.loadAllStories();
  }

  loadRisk(): void {
    const riskId = this.route.snapshot.paramMap.get('riskId');
    if (!riskId) {
      this.notFound.set(true);
      this.loading.set(false);
      return;
    }
    this.riskService.getRiskById(riskId).subscribe({
      next: (risk) => {
        this.risk.set(risk);
        this.loading.set(false);
      },
      error: (err) => {
        console.error('Failed to load risk:', err);
        this.notFound.set(true);
        this.loading.set(false);
        this.toast.error('Failed to load risk');
      }
    });
  }

  loadAllStories(): void {
    this.storiesService.getAllStories().subscribe({
      next: (stories) => this.allStories.set(stories),
      error: (err) => console.error('Failed to load stories:', err)
    });
  }

  // ============================================================
  // USER STORY HELPERS — PRIORITÉ À LA SOURCE STOCKÉE
  // ============================================================
  
  /** 
   * Récupère la description qui a SERVI à l'analyse de risque.
   * Priorité : source_story_text (stocké dans Risk) > story.description (fallback)
   */
  getStoryDescription(): string | null {
    const risk = this.risk();
    if (!risk) return null;

    // 1. Priorité : le texte source stocké dans le risque lui-même
    if (risk.source_story_text) {
      return risk.source_story_text;
    }

    // 2. Fallback : User Story originale (risques créés avant la feature)
    if (!risk.user_story_id) return null;
    const story = this.storyMap().get(risk.user_story_id);
    return story?.description || null;
  }

  /** 
   * Récupère les critères d'acceptation qui ont SERVI à l'analyse.
   * Priorité : source_acceptance_criteria (JSON stocké) > story.acceptance_criteria (fallback)
   */
  getStoryAcceptanceCriteria(): string[] | null {
    const risk = this.risk();
    if (!risk) return null;

    // 1. Priorité : les ACs stockés dans le risque (JSON string)
    if (risk.source_acceptance_criteria) {
      try {
        const parsed = JSON.parse(risk.source_acceptance_criteria);
        if (Array.isArray(parsed)) {
          return parsed.filter((c: string) => c && c.trim().length > 0);
        }
      } catch {
        console.warn('Failed to parse source_acceptance_criteria JSON');
      }
    }

    // 2. Fallback : User Story originale
    if (!risk.user_story_id) return null;
    const story = this.storyMap().get(risk.user_story_id);
    const criteria = story?.acceptance_criteria;
    if (!criteria || !Array.isArray(criteria)) return null;
    return criteria.filter((c: string) => c && c.trim().length > 0);
  }

  /** Label de la User Story */
  usLabel(): string {
    const risk = this.risk();
    if (!risk) return '—';
    return risk.user_story_key ?? 
           this.storyMap().get(risk.user_story_id || '')?.issue_key ?? 
           '—';
  }

  /** Titre de la User Story */
  usTitle(): string | null {
    const risk = this.risk();
    if (!risk?.user_story_id) return null;
    const story = this.storyMap().get(risk.user_story_id);
    return story?.title || null;
  }

  // ============================================================
  // MITIGATION EDITING
  // ============================================================

  startEditMitigation(): void {
    this.mitigationDraft = this.risk()?.mitigation || '';
    this.editingMitigation.set(true);
  }

  cancelEdit(): void {
    this.editingMitigation.set(false);
    this.mitigationDraft = '';
  }

  saveMitigation(): void {
    const risk = this.risk();
    if (!risk) return;

    this.saving.set(true);
    this.riskService.updateMitigation(risk.id, this.mitigationDraft).subscribe({
      next: (updatedRisk) => {
        this.risk.set(updatedRisk);
        this.editingMitigation.set(false);
        this.mitigationDraft = '';
        this.saving.set(false);
        this.toast.success('Mitigation saved');
      },
      error: () => {
        this.saving.set(false);
        this.toast.error('Failed to save mitigation');
      }
    });
  }

    startEditFormula(): void {
    const risk = this.risk();
    if (!risk) return;
    this.probabilityDraft = risk.probability;
    this.impactDraft = risk.impact;
    this.editingFormula.set(true);
  }

  cancelEditFormula(): void {
    this.editingFormula.set(false);
  }

  onProbabilityChange(value: number): void {
    // Clamp between 0.1 and 0.9
    this.probabilityDraft = Math.min(0.9, Math.max(0.1, value));
  }

  onImpactChange(value: number): void {
    // Clamp between 1 and 5
    this.impactDraft = Math.min(5, Math.max(1, Math.round(value)));
  }

  probBandLabelDraft(): string {
    const prob = this.probabilityDraft;
    if (prob >= 0.8) return 'Very High';
    if (prob >= 0.6) return 'High';
    if (prob >= 0.4) return 'Medium';
    if (prob >= 0.2) return 'Low';
    return 'Very Low';
  }

  impactLabelDraft(): string {
    const labels = ['Very Low', 'Low', 'Medium', 'High', 'Very High'];
    return labels[this.impactDraft - 1] || 'Unknown';
  }

  saveFormula(): void {
    const risk = this.risk();
    if (!risk) return;

    this.savingFormula.set(true);
    this.riskService.updateRisk(risk.id, {
      probability: this.probabilityDraft,
      impact: this.impactDraft,
    }).subscribe({
      next: (updatedRisk) => {
        this.risk.set(updatedRisk);
        this.editingFormula.set(false);
        this.savingFormula.set(false);
        this.toast.success('Risk score updated');
      },
      error: () => {
        this.savingFormula.set(false);
        this.toast.error('Failed to update risk score');
      }
    });
  }

  // ============================================================
  // RISK DECISION
  // ============================================================

acceptRisk(accepted: boolean): void {
  const risk = this.risk();
  if (!risk) return;
  
  this.riskService.acceptRisk(risk.id, accepted).subscribe({
    next: (updatedRisk) => {
      this.risk.set(updatedRisk);
      const action = accepted ? 'accepted' : 'rejected';
      this.toast.success(`Risk ${action} successfully!`);
      setTimeout(() => {
        this.router.navigate(['/risk-analysis'], {
          queryParams: { project: updatedRisk.project_id }
        });
      }, 1000);
    },
    error: () => {
      this.toast.error('Failed to update risk status');
    }
  });
}

  // ============================================================
  // UI HELPERS
  // ============================================================

  goBack(): void {
    this.router.navigate(['/risk-analysis'], {
      queryParams: { project: this.risk()?.project_id }
    });
  }

  formatScore(score: number): string {
    return score.toFixed(2);
  }

  probPercent(p: number): number {
    return Math.round(p * 100);
  }

  probBandLabel(): string {
    const prob = this.risk()?.probability ?? 0;
    if (prob >= 0.8) return 'Very High';
    if (prob >= 0.6) return 'High';
    if (prob >= 0.4) return 'Medium';
    if (prob >= 0.2) return 'Low';
    return 'Very Low';
  }

  impactLabel(): string {
    const impact = this.risk()?.impact ?? 0;
    const labels = ['Very Low', 'Low', 'Medium', 'High', 'Very High'];
    return labels[impact - 1] || 'Unknown';
  }

  acceptanceLabel(val: boolean | null): string {
    if (val === true) return 'Accepted';
    if (val === false) return 'Rejected';
    return 'Pending Review';
  }

  scoreBarPosition(score: number): number {
    return (score / 4.5) * 100;
  }
}