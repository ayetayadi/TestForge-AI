// pages.routes.ts
import { Routes } from '@angular/router';
import { CreateUserComponent } from './admin/create-user/create-user.component';
import { JiraConnectComponent } from './jira/jira-connect/jira-connect.component';
import { adminGuard } from '../core/guards/admin.guard';
import { authGuard } from '../core/guards/auth.guard';
import { ProfileComponent } from './profile/profile.component';
import { UserDashboardComponent } from './user/user-dashboard/user-dashboard.component';
import { AdminDashboardComponent } from './admin/admin-dashboard/admin-dashboard.component';
import { TestCasesComponent } from './test-cases/test-cases.component';
import { TestCaseDetailComponent } from './test-case-detail/test-case-detail.component';

export const PagesRoutes: Routes = [
  {
    path: 'user-dashboard',
    component: UserDashboardComponent,
    canActivate: [authGuard],
  },
  {
    path: 'projects',
    loadComponent: () =>
      import('./projects/projects.component').then(m => m.ProjectsComponent),
    canActivate: [authGuard],
    data: { title: 'Projects' },
  },
  {
    path: 'user-stories',
    loadComponent: () =>
      import('./user-stories/user-stories.component').then(m => m.UserStoriesComponent),
    canActivate: [authGuard],
    data: { title: 'User Stories' },
  },
  {
    path: 'user-stories/:storyId',
    loadComponent: () =>
      import('./user-story-detail/user-story-detail.component').then(m => m.UserStoryDetailComponent),
    canActivate: [authGuard],
    data: { title: 'User Story Detail' },
  },
  {
    path: 'review/:versionId',
    loadComponent: () =>
      import('./review/review.component').then(m => m.ReviewComponent),
    canActivate: [authGuard],
    data: { title: 'Review' },
  },
  {
    path: 'admin-dashboard',
    component: AdminDashboardComponent,
    canActivate: [adminGuard],
  },
  {
    path: 'admin/users',
    component: CreateUserComponent,
    canActivate: [adminGuard],
    data: { title: 'User Management' },
  },
  {
    path: 'jira',
    component: JiraConnectComponent,
    canActivate: [authGuard],
    data: { title: 'Jira Integration' },
  },
  {
    path: 'profile',
    component: ProfileComponent,
    canActivate: [authGuard],
    data: { title: 'Profile' },
  },
  {
    path: 'test-cases',
    component: TestCasesComponent,
    canActivate: [authGuard],
    data: { title: 'Test Cases' },
  },
  {
    path: 'test-cases/:id',
    component: TestCaseDetailComponent,
    canActivate: [authGuard],
    data: { title: 'Test Case Details' },
  },
  {
    path: 'playwright-scripts',
    loadComponent: () =>
      import('./playwright-scripts/playwright-scripts.component').then(m => m.PlaywrightScriptsComponent),
    canActivate: [authGuard],
    data: { title: 'Playwright Scripts' },
  },
  {
    path: 'playwright-scripts/:testCaseId',
    loadComponent: () =>
      import('./playwright-script-detail/playwright-script-detail.component').then(m => m.PlaywrightScriptDetailComponent),
    canActivate: [authGuard],
    data: { title: 'Script Detail' },
  },
  {
    path: 'risk-analysis',
    loadComponent: () =>
      import('./risk-analysis/risk-analysis.component').then(m => m.RiskAnalysisComponent),
    canActivate: [authGuard],
    data: { title: 'Risk Analysis' },
  },
  {
    path: 'risk-analysis/:riskId',
    loadComponent: () =>
      import('./risk-detail/risk-detail.component').then(m => m.RiskDetailComponent),
    canActivate: [authGuard],
    data: { title: 'Risk Detail' },
  },
  {
    path: 'test-plans',
    loadComponent: () =>
      import('./test-plans/test-plans.component').then(m => m.TestPlansComponent),
    canActivate: [authGuard],
    data: { title: 'Test Plans' },
  },
  {
    path: 'test-plans/:planId',
    loadComponent: () =>
      import('./test-plan-detail/test-plan-detail.component').then(m => m.TestPlanDetailComponent),
    canActivate: [authGuard],
    data: { title: 'Test Plan Detail' },
  },

];