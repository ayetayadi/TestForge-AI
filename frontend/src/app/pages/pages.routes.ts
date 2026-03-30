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
  },
  {
    path: 'admin-dashboard',
    component: AdminDashboardComponent,
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
  },
];
