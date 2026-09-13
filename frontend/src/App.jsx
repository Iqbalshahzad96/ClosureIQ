import React, { useState } from 'react';
import MainLayout from './layouts/MainLayout';
import DashboardPage from './pages/DashboardPage';
import ReconciliationPage from './pages/ReconciliationPage';
import ExceptionsPage from './pages/ExceptionsPage';
import ApprovalsPage from './pages/ApprovalsPage';
import ObservabilityPage from './pages/ObservabilityPage';
import FinancialUploadPage from './pages/FinancialUploadPage';

export default function App() {
  const [activeTab, setActiveTab] = useState('dashboard');

  const renderActivePage = () => {
    switch (activeTab) {
      case 'dashboard':
        return <DashboardPage setActiveTab={setActiveTab} />;
      case 'financial-upload':
        return <FinancialUploadPage setActiveTab={setActiveTab} />;
      case 'reconciliation':
        return <ReconciliationPage />;
      case 'exceptions':
        return <ExceptionsPage />;
      case 'approvals':
        return <ApprovalsPage />;
      case 'observability':
        return <ObservabilityPage />;
      default:
        return <DashboardPage setActiveTab={setActiveTab} />;
    }
  };

  return (
    <MainLayout activeTab={activeTab} setActiveTab={setActiveTab}>
      {renderActivePage()}
    </MainLayout>
  );
}
