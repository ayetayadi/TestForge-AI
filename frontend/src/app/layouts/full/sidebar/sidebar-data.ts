import { NavItem } from './nav-item/nav-item';

export const navItems: NavItem[] = [
  {
    navCap: 'Home',
  },
  {
    displayName: 'admin Dashboard',
    iconName: 'solar:widget-add-line-duotone',
    route: '/dashboard',
  },
  {
    displayName: 'Projects',
    iconName: 'solar:folder-with-files-line-duotone',
    route: '/dashboard/projects',
  },
  {
    displayName: 'User Stories',
    iconName: 'solar:document-text-line-duotone',
    route: '/dashboard/user-stories',
  },


  {
    displayName: 'admin Dashboard',
    iconName: 'solar:widget-add-line-duotone',
    route: '/admin-dashboard',
    adminOnly: true,
  },
  {
    displayName: 'user Dashboard',
    iconName: 'solar:widget-add-line-duotone',
    route: '/user-dashboard',
    userOnly: true,
  },
  {
    navCap: 'Admin',
    divider: true,
    adminOnly: true,
  },
  // ============ EXTRA ============
  {
    navCap: 'Extra',
    divider: true
  },
  {
    displayName: 'Icons',
    iconName: 'solar:sticker-smile-circle-2-line-duotone',
    route: '/extra/icons',
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
    displayName: 'Connect Jira',
    iconName: 'solar:link-circle-line-duotone',
    route: '/jira',
    userOnly: true,
  },
];
