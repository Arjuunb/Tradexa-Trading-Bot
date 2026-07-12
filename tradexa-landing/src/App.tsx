import { lazy, Suspense } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Background } from "@/components/landing/Background";
import { ToastProvider } from "@/lib/toast";
import { Skeleton } from "@/components/ui/Skeleton";

// Landing renders eagerly (it's the entry point); auth pages are code-split so
// the marketing page ships the smallest possible bundle.
import Landing from "@/pages/Landing";
const Login = lazy(() => import("@/pages/auth/Login"));
const Register = lazy(() => import("@/pages/auth/Register"));
const ForgotPassword = lazy(() => import("@/pages/auth/ForgotPassword"));
const ResetPassword = lazy(() => import("@/pages/auth/ResetPassword"));
const VerifyEmail = lazy(() => import("@/pages/auth/VerifyEmail"));
const TwoFactor = lazy(() => import("@/pages/auth/TwoFactor"));
const SessionExpired = lazy(() => import("@/pages/auth/SessionExpired"));

function AuthFallback() {
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

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <Background />
        <Suspense fallback={<AuthFallback />}>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/auth/login" element={<Login />} />
            <Route path="/auth/register" element={<Register />} />
            <Route path="/auth/forgot-password" element={<ForgotPassword />} />
            <Route path="/auth/reset-password" element={<ResetPassword />} />
            <Route path="/auth/verify-email" element={<VerifyEmail />} />
            <Route path="/auth/two-factor" element={<TwoFactor />} />
            <Route path="/auth/session-expired" element={<SessionExpired />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </Suspense>
      </ToastProvider>
    </BrowserRouter>
  );
}
