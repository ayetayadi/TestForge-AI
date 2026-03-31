import { Routes } from '@angular/router';
import { AppSideLoginComponent } from './side-login/side-login.component';
import { SetupPasswordComponent } from './setup-password/setup-password.component';
import { guestGuard } from 'src/app/core/guards/guest.guard';
import {ForgotPasswordComponent} from "./forgot-password/forgot-password.component";
import {ResetPasswordComponent} from "./reset-password/reset-password.component";

export const AuthenticationRoutes: Routes = [
  {
    path: '',
    children: [
      { path: 'login', component: AppSideLoginComponent, canActivate: [guestGuard] },
      { path: 'setup-password', component: SetupPasswordComponent },
      { path: 'forgot-password', component: ForgotPasswordComponent },
      { path: 'reset-password',  component: ResetPasswordComponent  },
    ],
  },
];
