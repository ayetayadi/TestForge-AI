import { NavItem } from './nav-item/nav-item';

export const navItems: NavItem[] = [
  {
    navCap: 'Home',
  },
  {
    displayName: 'Admin Dashboard',
    iconName: 'solar:widget-add-line-duotone',
    route: '/admin-dashboard',
    adminOnly: true,
  },
  {
    displayName: 'User Dashboard',
    iconName: 'solar:widget-add-line-duotone',
    route: '/user-dashboard',
    userOnly: true,
  },
  {
    displayName: 'Projects',
    iconName: 'solar:folder-with-files-line-duotone',
    route: '/projects',
    userOnly: true,
  },
  {
    displayName: 'User Stories',
    iconName: 'solar:document-text-line-duotone',
    route: '/user-stories',
    userOnly: true,
  },
  {
    navCap: 'Admin',
    divider: true,
    adminOnly: true,
  },
  {
    displayName: 'Manage Users',
    iconName: 'solar:users-group-rounded-line-duotone',
    route: '/admin/users',
    adminOnly: true,
  },
  {
    navCap: 'Integrations',
    divider: true,
    userOnly: true,
  },
  {
    displayName: 'Paramètres',
    iconName: 'solar:link-circle-line-duotone',
    route: '/jira',
    userOnly: true,
  },
];
