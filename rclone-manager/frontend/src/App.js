import React, { useState, useEffect, useLayoutEffect } from 'react';
import { Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Sidebar from './components/Sidebar';
import ThemeToggle from './components/ThemeToggle';
import Dashboard from './pages/Dashboard';
import Tasks from './pages/Tasks';
import TaskDetail from './pages/TaskDetail';
import TaskForm from './pages/TaskForm';
import Logs from './pages/Logs';
import Settings from './pages/Settings';
import FileBrowser from './pages/FileBrowser';
import OpenlistConfigs from './pages/OpenlistConfigs';
import Mounts from './pages/Mounts';
import Dedupe from './pages/Dedupe';
import DedupeTaskDetail from './pages/DedupeTaskDetail';
import Login from './pages/Login';
import useAuthStore from './hooks/useAuthStore';

function App() {
  const { isAuthenticated, checkAuth } = useAuthStore();
  const [authChecked, setAuthChecked] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [theme, setTheme] = useState(() => {
    try {
      return window.localStorage.getItem('rclone-manager-theme') === 'dark' ? 'dark' : 'light';
    } catch (_) {
      return 'light';
    }
  });
  const location = useLocation();

  useLayoutEffect(() => {
    document.documentElement.classList.toggle('theme-dark', theme === 'dark');
    document.documentElement.style.colorScheme = theme;
    try {
      window.localStorage.setItem('rclone-manager-theme', theme);
    } catch (_) {
      // Private browsing can disable local storage; the switch still works.
    }
  }, [theme]);

  const toggleTheme = () => setTheme((current) => current === 'dark' ? 'light' : 'dark');
  const toastOptions = {
    style: theme === 'dark'
      ? { background: '#1e293b', color: '#f1f5f9', border: '1px solid #334155' }
      : {},
  };

  useEffect(() => {
    checkAuth();
    setAuthChecked(true);
  }, [checkAuth]);

  // Close sidebar on mobile
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 768) {
        setSidebarOpen(false);
      } else {
        setSidebarOpen(true);
      }
    };
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  // Show loading while checking auth
  if (!authChecked) {
    return (
      <div className="min-h-screen bg-gray-100 flex items-center justify-center">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (!isAuthenticated && location.pathname !== '/login') {
    return <Navigate to="/login" replace />;
  }

  if (location.pathname === '/login') {
    if (isAuthenticated) {
      return <Navigate to="/" replace />;
    }
    return (
      <>
        <Login />
        <Toaster position="top-right" toastOptions={toastOptions} />
      </>
    );
  }

  return (
    <div className="flex h-screen bg-gray-50">
      <Sidebar open={sidebarOpen} setOpen={setSidebarOpen} />

      <div className={`flex-1 flex flex-col transition-all duration-300 min-w-0 ${sidebarOpen ? 'md:ml-64' : 'ml-0'}`}>
        {/* Mobile header */}
        <div className="md:hidden bg-white border-b border-gray-200 px-4 py-3 flex items-center shadow-sm">
          <button 
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 rounded-lg hover:bg-gray-100 text-gray-700"
          >
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <span className="ml-3 font-semibold text-gray-800">Rclone Manager</span>
          <div className="ml-auto"><ThemeToggle theme={theme} onToggle={toggleTheme} /></div>
        </div>

        <div className="hidden md:flex justify-end px-6 py-2 bg-gray-50">
          <ThemeToggle theme={theme} onToggle={toggleTheme} />
        </div>

        <main className="flex-1 overflow-auto p-3 md:p-6 min-w-0">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/tasks" element={<Tasks />} />
            <Route path="/tasks/new" element={<TaskForm />} />
            <Route path="/tasks/:id" element={<TaskDetail />} />
            <Route path="/tasks/:id/edit" element={<TaskForm />} />
            <Route path="/logs" element={<Logs />} />
            <Route path="/files" element={<FileBrowser />} />
            <Route path="/dedupe" element={<Dedupe />} />
            <Route path="/dedupe-tasks/:id" element={<DedupeTaskDetail />} />
            <Route path="/mounts" element={<Mounts />} />
            <Route path="/openlist-configs" element={<OpenlistConfigs />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </main>
      </div>

      <Toaster position="top-right" toastOptions={toastOptions} />
    </div>
  );
}

export default App;
