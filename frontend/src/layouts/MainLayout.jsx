import React, { useState } from 'react';
import Header from '../components/Header';
import Sidebar from '../components/Sidebar';
import { useHealth } from '../hooks/useHealth';

export default function MainLayout({ children, activeTab, setActiveTab }) {
  const { health } = useHealth();

  return (
    <div className="app-container">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      <div className="main-content-area">
        <Header healthStatus={health} />
        <main className="page-body">
          {children}
        </main>
      </div>
    </div>
  );
}
