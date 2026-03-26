import { Routes } from '@angular/router';
import { AppSideLoginComponent } from './side-login/side-login.component';
import { ChangePasswordComponent } from './change-password/change-password.component';
import { SetupPasswordComponent } from './setup-password/setup-password.component';
import { guestGuard } from 'src/app/core/guards/guest.guard';

export const AuthenticationRoutes: Routes = [
  {
    path: '',
    children: [
      { path: 'login', component: AppSideLoginComponent, canActivate: [guestGuard] },
      { path: 'change-password', component: ChangePasswordComponent },
      { path: 'setup-password', component: SetupPasswordComponent },  // ← new
    ],
  },
];
