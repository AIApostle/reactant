import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import App from './App'
import AgentCardCheckout from './AgentCardCheckout'
import { AuthPage, LandingPage, NotFoundPage } from './PublicSite'

export default function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/signup" element={<AuthPage mode="signup" />} />
        <Route path="/checkout/:token" element={<AgentCardCheckout />} />
        <Route path="/app" element={<App />} />
        <Route path="/app/*" element={<Navigate to="/app" replace />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  )
}
