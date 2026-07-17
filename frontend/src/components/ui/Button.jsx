import React from 'react';

/**
 * One button for the whole app. variant: primary | secondary | ghost | danger.
 * Pass `icon` alone (no children) for a square icon button. Replaces the ~101
 * bespoke .btn-* classes. Token-driven, so it flips light/dark automatically.
 */
export default function Button({
  variant = 'secondary',
  size,
  icon,
  iconRight,
  className = '',
  type = 'button',
  children,
  ...props
}) {
  const iconOnly = icon && children == null;
  const cls = [
    'ui-btn',
    `ui-btn--${variant}`,
    size === 'sm' ? 'ui-btn--sm' : '',
    iconOnly ? 'ui-btn--icon' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');
  return (
    <button type={type} className={cls} {...props}>
      {icon}
      {children}
      {iconRight}
    </button>
  );
}
