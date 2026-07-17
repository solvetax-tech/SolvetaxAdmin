/**
 * @file main.jsx
 * @description The main entry point of the React frontend application.
 * It strictly mounts the `<App />` component into the root DOM node
 * wrapper configured with React.StrictMode for development warnings.
 */
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import './styles/ui.css'
import App from './App.jsx'
import { initTheme } from './utils/themeManager'

// Apply persisted theme before first paint to avoid a flash of the wrong theme.
initTheme()

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
