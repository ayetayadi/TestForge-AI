import { Routes } from '@angular/router';

export const PagesRoutes: Routes = [
  {
    path: '',
    children: [
      {
        path: '',
        loadComponent: () => import('./starter/starter.component').then(m => m.StarterComponent),
        data: {
          title: 'Dashboard',
        },
      },

      {
        path: 'projects',
        loadComponent: () => import('./projects/projects.component').then(m => m.ProjectsComponent),
        data: { title: 'Projects' },
      },
      {
        path: 'user-stories',
        loadComponent: () => import('./user-stories/user-stories.component').then(m => m.UserStoriesComponent),
        data: { title: 'User Stories' },
      },
      {
        path: 'review/:jobId',
        loadComponent: () => import('./review/review.component').then(m => m.ReviewComponent),
        data: { title: 'Review' },
      }
    ],
  },
];