import { Routes } from '@angular/router';
import { CreateUserComponent } from './admin/create-user/create-user.component';
import { JiraConnectComponent } from './jira/jira-connect/jira-connect.component';
import { adminGuard } from '../core/guards/admin.guard';
import { authGuard } from '../core/guards/auth.guard';
import { ProfileComponent } from './profile/profile.component';
import { UserDashboardComponent } from './user/user-dashboard/user-dashboard.component';
import { AdminDashboardComponent } from './admin/admin-dashboard/admin-dashboard.component';

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
    path: 'review/:jobId',
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
];
