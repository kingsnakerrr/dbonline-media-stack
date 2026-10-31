import React from 'react';
import { Moon, Sun } from 'lucide-react';

const ThemeToggle = ({ theme, onToggle }) => {
  const isDark = theme === 'dark';
  const label = isDark ? '开灯' : '关灯';
  return (
    <button
      type="button"
      onClick={onToggle}
      title={`${label} · 切换到${isDark ? '浅色' : '暗黑'}主题`}
      aria-label={`切换到${isDark ? '浅色' : '暗黑'}主题`}
      aria-pressed={isDark}
      className="inline-flex items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-700 shadow-sm transition-colors hover:bg-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
    >
      {isDark ? <Sun className="h-4 w-4 text-amber-500" /> : <Moon className="h-4 w-4 text-blue-600" />}
      <span>{label}</span>
    </button>
  );
};

export default ThemeToggle;
