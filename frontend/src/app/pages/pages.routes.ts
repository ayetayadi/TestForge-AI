import { Routes } from '@angular/router';
import { StarterComponent } from './starter/starter.component';
import { CreateUserComponent } from './admin/create-user/create-user.component';
import { JiraConnectComponent } from './jira/jira-connect/jira-connect.component';
import { adminGuard } from '../core/guards/admin.guard';
import { authGuard } from '../core/guards/auth.guard';
import {ProfileComponent} from "./profile/profile.component";

export const PagesRoutes: Routes = [
  {
    path: '',
    component: StarterComponent,
    data: { title: 'Starter', urls: [{ title: 'Dashboard', url: '/dashboard' }, { title: 'Starter' }] },
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
  { path: 'profile', component: ProfileComponent }

];
