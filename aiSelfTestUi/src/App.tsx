import React, { useState, useEffect } from 'react';
import { LayoutDashboard, Users, ListTodo, Activity, CheckSquare, Settings, Moon, Sun, Cpu, MessageSquare, FileText } from 'lucide-react';
import Dashboard from './components/Dashboard';
import Clients from './components/Clients';
import Tasks from './components/Tasks';
import CreateTask from './components/CreateTask';
import DataQuery from './components/DataQuery';
import Review from './components/Review';
import MultimodalModels from './components/MultimodalModels';
import MultimodalChat from './components/MultimodalChat';
import PromptConfigs from './components/PromptConfigs';

type View = 'dashboard' | 'clients' | 'tasks' | 'create-task' | 'data-query' | 'review' | 'multimodal-models' | 'multimodal-chat' | 'prompt-configs';

export default function App() {
  const [currentView, setCurrentView] = useState<View>('dashboard');
  const [selectedTaskId, setSelectedTaskId] = useState<number | null>(null);
  const [selectedReviewTaskId, setSelectedReviewTaskId] = useState<number | null>(null);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDark]);

  const renderView = () => {
    switch (currentView) {
      case 'dashboard': return <Dashboard />;
      case 'clients': return <Clients />;
      case 'tasks': return <Tasks 
        onCreateTask={() => setCurrentView('create-task')} 
        onQueryData={(taskId: number) => { setSelectedTaskId(taskId); setCurrentView('data-query'); }}
        onReview={(taskId: number) => { setSelectedReviewTaskId(taskId); setCurrentView('review'); }}
      />;
      case 'create-task': return <CreateTask onBack={() => setCurrentView('tasks')} />;
      case 'data-query': return <DataQuery taskId={selectedTaskId!} onBack={() => setCurrentView('tasks')} />;
      case 'review': return <Review initialTaskId={selectedReviewTaskId} />;
      case 'multimodal-models': return <MultimodalModels />;
      case 'multimodal-chat': return <MultimodalChat onOpenModelManager={() => setCurrentView('multimodal-models')} />;
      case 'prompt-configs': return <PromptConfigs />;
      default: return <Dashboard />;
    }
  };

  return (
    <div className="flex h-screen bg-gray-50 dark:bg-gray-900 font-sans text-gray-900 dark:text-gray-100 transition-colors duration-200">
      {/* Sidebar */}
      <aside className="w-64 bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 flex flex-col transition-colors duration-200">
        <div className="p-6 border-b border-gray-200 dark:border-gray-700">
          <h1 className="text-xl font-bold text-gray-900 dark:text-white flex items-center gap-2">
            <Activity className="w-6 h-6 text-blue-600 dark:text-blue-400" />
            CloudyTrack 人工智能自检系统
          </h1>
        </div>
        <nav className="flex-1 p-4 space-y-1">
          <NavItem icon={<LayoutDashboard />} label="总览" active={currentView === 'dashboard'} onClick={() => setCurrentView('dashboard')} />
          <NavItem icon={<Users />} label="客户端管理" active={currentView === 'clients'} onClick={() => setCurrentView('clients')} />
          <NavItem icon={<ListTodo />} label="任务管理" active={currentView === 'tasks'} onClick={() => setCurrentView('tasks')} />
          <NavItem icon={<CheckSquare />} label="结果复核" active={currentView === 'review'} onClick={() => { setSelectedReviewTaskId(null); setCurrentView('review'); }} />
          <NavItem icon={<Cpu />} label="模型管理" active={currentView === 'multimodal-models'} onClick={() => setCurrentView('multimodal-models')} />
          <NavItem icon={<MessageSquare />} label="模型测试" active={currentView === 'multimodal-chat'} onClick={() => setCurrentView('multimodal-chat')} />
          <NavItem icon={<FileText />} label="提示词配置" active={currentView === 'prompt-configs'} onClick={() => setCurrentView('prompt-configs')} />
        </nav>
        <div className="p-4 border-t border-gray-200 dark:border-gray-700 space-y-2">
          <button 
            onClick={() => setIsDark(!isDark)}
            className="flex items-center gap-3 px-3 py-2 w-full text-left text-sm font-medium text-gray-600 dark:text-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            {isDark ? <Sun className="w-5 h-5" /> : <Moon className="w-5 h-5" />}
            {isDark ? '白天模式' : '黑夜模式'}
          </button>
          <button className="flex items-center gap-3 px-3 py-2 w-full text-left text-sm font-medium text-gray-600 dark:text-gray-300 rounded-md hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">
            <Settings className="w-5 h-5" />
            设置
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto">
        {renderView()}
      </main>
    </div>
  );
}

function NavItem({ icon, label, active, onClick }: { icon: React.ReactNode, label: string, active: boolean, onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`flex items-center gap-3 px-3 py-2 w-full text-left text-sm font-medium rounded-md transition-colors ${
        active 
          ? 'bg-blue-50 dark:bg-blue-900/50 text-blue-700 dark:text-blue-400' 
          : 'text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-700 hover:text-gray-900 dark:hover:text-gray-100'
      }`}
    >
      {React.cloneElement(icon as React.ReactElement, { className: 'w-5 h-5' })}
      {label}
    </button>
  );
}
