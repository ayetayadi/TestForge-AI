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
    displayName: 'Risk Analysis',
    iconName: 'solar:danger-triangle-line-duotone',
    route: '/risk-analysis',
    userOnly: true,
  },
  {
    displayName: 'Test Plans',
    iconName: 'solar:clipboard-list-line-duotone',
    route: '/test-plans',
    userOnly: true,
  },
  {
    displayName: 'Test Cases',
    iconName: 'solar:document-add-line-duotone',
    route: '/test-cases',
    userOnly: true,
  },
  {
    displayName: 'Playwright Scripts',
    iconName: 'solar:play-circle-line-duotone',
    route: '/playwright-scripts',
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
    displayName: 'Settings',
    iconName: 'solar:link-circle-line-duotone',
    route: '/jira',
    userOnly: true,
  },
];
