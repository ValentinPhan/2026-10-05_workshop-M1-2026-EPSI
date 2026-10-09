import React from 'react';
import { createRoot } from 'react-dom/client';
import { App as AntApp, ConfigProvider, theme } from 'antd';
import frFR from 'antd/locale/fr_FR';
import '@fontsource-variable/bricolage-grotesque';
import '@fontsource-variable/geist';
import '@fontsource-variable/geist-mono';
import App from './App.jsx';
import './styles.css';

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <ConfigProvider
      locale={frFR}
      theme={{
        algorithm: theme.darkAlgorithm,
        token: {
          colorPrimary: '#ffd83b',
          colorInfo: '#5b9bf0',
          colorSuccess: '#3ecf8e',
          colorWarning: '#f5a524',
          colorError: '#ff5a4f',
          colorBgBase: '#0b0d12',
          colorBgContainer: '#12151c',
          colorBgElevated: '#181c25',
          colorBorder: '#2d3340',
          colorBorderSecondary: '#222733',
          borderRadius: 10,
          borderRadiusLG: 16,
          fontFamily: "'Geist Variable', system-ui, -apple-system, 'Segoe UI', sans-serif",
          fontFamilyCode: "'Geist Mono Variable', ui-monospace, monospace",
        },
        components: { Button: { primaryColor: '#1a1400', colorTextLightSolid: '#1a1400' } },
      }}
    >
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  </React.StrictMode>,
);
