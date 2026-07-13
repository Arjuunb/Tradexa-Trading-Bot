import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Background } from "@/components/landing/Background";
import { ToastProvider } from "@/lib/toast";
import { Skeleton } from "@/components/ui/Skeleton";
import { SettingsProvider, useApplyAppearance } from "@/settings/store";

// Landing renders eagerly (it's the entry point); auth + settings are code-split
// so the marketing page ships the smallest possible bundle.
import Landing from "@/pages/Landing";
const Login = lazy(() => import("@/pages/auth/Login"));
const Register = lazy(() => import("@/pages/auth/Register"));
const ForgotPassword = lazy(() => import("@/pages/auth/ForgotPassword"));
const ResetPassword = lazy(() => import("@/pages/auth/ResetPassword"));
const VerifyEmail = lazy(() => import("@/pages/auth/VerifyEmail"));
const TwoFactor = lazy(() => import("@/pages/auth/TwoFactor"));
const SessionExpired = lazy(() => import("@/pages/auth/SessionExpired"));

const SettingsLayout = lazy(() => import("@/components/settings/SettingsLayout"));
const SettingsOverview = lazy(() => import("@/pages/settings/Overview"));
const Profile = lazy(() => import("@/pages/settings/Profile"));
const Account = lazy(() => import("@/pages/settings/Account"));
const Security = lazy(() => import("@/pages/settings/Security"));
const Notifications = lazy(() => import("@/pages/settings/Notifications"));
const Trading = lazy(() => import("@/pages/settings/Trading"));
const Exchanges = lazy(() => import("@/pages/settings/Exchanges"));
const Strategies = lazy(() => import("@/pages/settings/Strategies"));
const Risk = lazy(() => import("@/pages/settings/Risk"));
const AI = lazy(() => import("@/pages/settings/AI"));
const Automation = lazy(() => import("@/pages/settings/Automation"));
const Scheduler = lazy(() => import("@/pages/settings/Scheduler"));
const Portfolio = lazy(() => import("@/pages/settings/Portfolio"));
const ApiKeys = lazy(() => import("@/pages/settings/ApiKeys"));
const Integrations = lazy(() => import("@/pages/settings/Integrations"));
const Team = lazy(() => import("@/pages/settings/Team"));
const Billing = lazy(() => import("@/pages/settings/Billing"));
const Usage = lazy(() => import("@/pages/settings/Usage"));
const Logs = lazy(() => import("@/pages/settings/Logs"));
const Audit = lazy(() => import("@/pages/settings/Audit"));
const Backup = lazy(() => import("@/pages/settings/Backup"));
const Appearance = lazy(() => import("@/pages/settings/Appearance"));
const Region = lazy(() => import("@/pages/settings/Region"));
const Privacy = lazy(() => import("@/pages/settings/Privacy"));
const Advanced = lazy(() => import("@/pages/settings/Advanced"));
const Danger = lazy(() => import("@/pages/settings/Danger"));

function Fallback() {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-sm space-y-4">
        <Skeleton className="h-10 w-32" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
        <Skeleton className="h-11 w-full" />
      </div>
    </div>
  );
}

function AppearanceApplier() {
  useApplyAppearance();
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <SettingsProvider>
        <ToastProvider>
          <AppearanceApplier />
          <Background />
          <Suspense fallback={<Fallback />}>
            <Routes>
              <Route path="/" element={<Landing />} />

              <Route path="/auth/login" element={<Login />} />
              <Route path="/auth/register" element={<Register />} />
              <Route path="/auth/forgot-password" element={<ForgotPassword />} />
              <Route path="/auth/reset-password" element={<ResetPassword />} />
              <Route path="/auth/verify-email" element={<VerifyEmail />} />
              <Route path="/auth/two-factor" element={<TwoFactor />} />
              <Route path="/auth/session-expired" element={<SessionExpired />} />

              <Route path="/settings" element={<SettingsLayout />}>
                <Route index element={<Navigate to="/settings/overview" replace />} />
                <Route path="overview" element={<SettingsOverview />} />
                <Route path="profile" element={<Profile />} />
                <Route path="account" element={<Account />} />
                <Route path="security" element={<Security />} />
                <Route path="notifications" element={<Notifications />} />
                <Route path="trading" element={<Trading />} />
                <Route path="exchanges" element={<Exchanges />} />
                <Route path="strategies" element={<Strategies />} />
                <Route path="risk" element={<Risk />} />
                <Route path="ai" element={<AI />} />
                <Route path="automation" element={<Automation />} />
                <Route path="scheduler" element={<Scheduler />} />
                <Route path="portfolio" element={<Portfolio />} />
                <Route path="api-keys" element={<ApiKeys />} />
                <Route path="integrations" element={<Integrations />} />
                <Route path="team" element={<Team />} />
                <Route path="billing" element={<Billing />} />
                <Route path="usage" element={<Usage />} />
                <Route path="logs" element={<Logs />} />
                <Route path="audit" element={<Audit />} />
                <Route path="backup" element={<Backup />} />
                <Route path="appearance" element={<Appearance />} />
                <Route path="region" element={<Region />} />
                <Route path="privacy" element={<Privacy />} />
                <Route path="advanced" element={<Advanced />} />
                <Route path="danger" element={<Danger />} />
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </ToastProvider>
      </SettingsProvider>
    </BrowserRouter>
  );
}
