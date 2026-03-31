import { Component } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-user-dashboard',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './user-dashboard.component.html',
  styleUrls: ['./user-dashboard.component.scss']
})
export class UserDashboardComponent {
  stats = {
    userStories: 47,
    userStoriesWeekly: 8,
    testCases: 180,
    testCasesWeekly: 23,
    successRate: 87,
    successRateWeekly: 3.2,
    qualityScore: 74,
    qualityScoreWeekly: -2
  };

  coverageByCategory = [
    { label: 'Fonctionnel', value: 85 },
    { label: 'Régression', value: 60 },
    { label: 'Performance', value: 30 },
    { label: 'Sécurité', value: 45 },
    { label: 'UI/UX', value: 70 }
  ];

  testStatus = [
    { label: 'Réussi', value: 124, colorClass: 'green' },
    { label: 'Échoué', value: 18, colorClass: 'red' },
    { label: 'Bloqué', value: 7, colorClass: 'orange' },
    { label: 'En attente', value: 31, colorClass: 'gray' }
  ];

  recentActivities = [
    { message: '5 nouveaux cas de test générés à partir de Jira', time: 'Il y a 2 heures' },
    { message: 'Une user story a été synchronisée depuis Jira', time: 'Il y a 4 heures' },
    { message: 'Le script Playwright a été généré avec succès', time: 'Hier' },
    { message: 'Export des cas de test vers Squash TM effectué', time: 'Hier' }
  ];
}
