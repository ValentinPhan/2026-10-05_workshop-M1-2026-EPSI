import React from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp, ConfigProvider, theme } from 'antd';
import frFR from 'antd/locale/fr_FR';
import App from './App.jsx';
import './styles.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider
      locale={frFR}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: { colorPrimary: '#4fc3dc', colorBgBase: '#0a0e13', borderRadiusLG: 12 },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
